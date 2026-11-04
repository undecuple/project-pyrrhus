/* gpu_post_test.c -- GPU check of the post-chain compute kernels: runs port/kz2/spu/gpu_post_hlsl.h on
 * D3D12 (Windows / Proton) over the cases tools/spu/native_diff_harness.c exported from recorded game states
 * (KZ2_GPU_CASES: per case u32 slot, u32 nq, source row 0, source row 1, the lifted SPU code's output) and compares the
 * GPU's output with the lifted output byte for byte.
 *
 *   gpu_post_test.exe CASES [mutate]     prints "T gpu cases=N match=M mismatch=K adapter=..." and exits 0 when all match;
 *                                        "mutate" compiles the truncating average (the check must then fail).
 * Build (tools/spu/test_gpu_post.sh): x86_64-w64-mingw32-gcc -O2 -I port/kz2/spu tools/spu/gpu_post_test.c
 *   -ld3d12 -ldxgi -ld3dcompiler -ldxguid. Run only under Proton through the gpu lock. */
#define COBJMACROS
#define INITGUID
#define WIDL_C_INLINE_WRAPPERS
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <d3dcompiler.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gpu_post_hlsl.h"

typedef struct { uint32_t slot, nq, in_off, out_off; } tcase;

static ID3D12Resource* buffer(ID3D12Device* dev, D3D12_HEAP_TYPE type, UINT64 size, D3D12_RESOURCE_FLAGS fl,
                              D3D12_RESOURCE_STATES st)
{
    D3D12_HEAP_PROPERTIES hp = {0}; hp.Type = type;
    D3D12_RESOURCE_DESC rd = {0};
    rd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; rd.Width = size; rd.Height = 1; rd.DepthOrArraySize = 1;
    rd.MipLevels = 1; rd.SampleDesc.Count = 1; rd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; rd.Flags = fl;
    ID3D12Resource* r = NULL;
    if (FAILED(ID3D12Device_CreateCommittedResource(dev, &hp, D3D12_HEAP_FLAG_NONE, &rd, st, NULL, &IID_ID3D12Resource,
                                                    (void**)&r))) return NULL;
    return r;
}

int main(int argc, char** argv)
{
    if (argc < 2) { fprintf(stderr, "usage: gpu_post_test CASES [mutate]\n"); return 2; }
    const int mutate = argc > 2 && !strcmp(argv[2], "mutate");
    FILE* f = fopen(argv[1], "rb");
    if (!f) { printf("T gpu cannot open %s\n", argv[1]); return 2; }
    fseek(f, 0, SEEK_END); const long fsz = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t* raw = (uint8_t*)malloc((size_t)fsz);
    if (!raw || fread(raw, 1, (size_t)fsz, f) != (size_t)fsz) { printf("T gpu read failed\n"); return 2; }
    fclose(f);
    /* index the cases; the input buffer is the file itself (rows at their file offsets) */
    tcase* cs = NULL; size_t n = 0, cap = 0, out_total = 0;
    for (long o = 0; o + 8 <= fsz;) {
        uint32_t h[2]; memcpy(h, raw + o, 8);
        const long need = 8 + 80L * h[1];
        if (o + need > fsz || !h[1]) { printf("T gpu truncated case at %ld\n", o); return 2; }
        if (n == cap) { cap = cap ? cap * 2 : 256; cs = (tcase*)realloc(cs, cap * sizeof *cs); }
        cs[n].slot = h[0]; cs[n].nq = h[1]; cs[n].in_off = (uint32_t)(o + 8); cs[n].out_off = (uint32_t)out_total;
        out_total += 16u * h[1]; n++; o += need;
    }
    ID3D12Device* dev = NULL;
    if (FAILED(D3D12CreateDevice(NULL, D3D_FEATURE_LEVEL_11_0, &IID_ID3D12Device, (void**)&dev))) {
        printf("T gpu no D3D12 device\n"); return 3;
    }
    char adapter[128] = "?";
    {
        IDXGIFactory4* fac = NULL; IDXGIAdapter1* ad = NULL; DXGI_ADAPTER_DESC1 dd;
        const LUID luid = ID3D12Device_GetAdapterLuid(dev);
        if (SUCCEEDED(CreateDXGIFactory1(&IID_IDXGIFactory4, (void**)&fac)) &&
            SUCCEEDED(IDXGIFactory4_EnumAdapterByLuid(fac, luid, &IID_IDXGIAdapter1, (void**)&ad)) &&
            SUCCEEDED(IDXGIAdapter1_GetDesc1(ad, &dd)))
            WideCharToMultiByte(CP_UTF8, 0, dd.Description, -1, adapter, sizeof adapter, NULL, NULL);
        for (char* p = adapter; *p; p++) if (*p == ' ') *p = '_';
    }
    /* shader */
    const D3D_SHADER_MACRO mut[] = { { "KZ2_GPU_POST_MUTATE", "1" }, { NULL, NULL } };
    ID3DBlob* cso = NULL; ID3DBlob* err = NULL;
    if (FAILED(D3DCompile(kz2_gpu_post_hlsl, sizeof kz2_gpu_post_hlsl - 1, "kz2_gpu_post", mutate ? mut : NULL, NULL,
                          "main", "cs_5_0", D3DCOMPILE_IEEE_STRICTNESS, 0, &cso, &err))) {
        printf("T gpu compile failed: %s\n", err ? (const char*)ID3D10Blob_GetBufferPointer(err) : "?"); return 3;
    }
    /* root signature: 8 constants (b0), root SRV (t0), root UAV (u0) */
    D3D12_ROOT_PARAMETER rp[3]; memset(rp, 0, sizeof rp);
    rp[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; rp[0].Constants.Num32BitValues = 8;
    rp[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    rp[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    for (int i = 0; i < 3; i++) rp[i].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC rsd = {0}; rsd.NumParameters = 3; rsd.pParameters = rp;
    ID3DBlob* rsb = NULL;
    ID3D12RootSignature* rs = NULL;
    if (FAILED(D3D12SerializeRootSignature(&rsd, D3D_ROOT_SIGNATURE_VERSION_1, &rsb, &err)) ||
        FAILED(ID3D12Device_CreateRootSignature(dev, 0, ID3D10Blob_GetBufferPointer(rsb), ID3D10Blob_GetBufferSize(rsb),
                                                &IID_ID3D12RootSignature, (void**)&rs))) { printf("T gpu root signature failed\n"); return 3; }
    D3D12_COMPUTE_PIPELINE_STATE_DESC pd = {0};
    pd.pRootSignature = rs;
    pd.CS.pShaderBytecode = ID3D10Blob_GetBufferPointer(cso); pd.CS.BytecodeLength = ID3D10Blob_GetBufferSize(cso);
    ID3D12PipelineState* pso = NULL;
    if (FAILED(ID3D12Device_CreateComputePipelineState(dev, &pd, &IID_ID3D12PipelineState, (void**)&pso))) {
        printf("T gpu PSO failed\n"); return 3;
    }
    /* buffers */
    const UINT64 in_size = ((UINT64)fsz + 255) & ~255ull, out_size = ((UINT64)out_total + 255) & ~255ull;
    ID3D12Resource* bin = buffer(dev, D3D12_HEAP_TYPE_UPLOAD, in_size, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
    ID3D12Resource* bout = buffer(dev, D3D12_HEAP_TYPE_DEFAULT, out_size, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                                  D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    ID3D12Resource* brb = buffer(dev, D3D12_HEAP_TYPE_READBACK, out_size, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
    if (!bin || !bout || !brb) { printf("T gpu buffers failed\n"); return 3; }
    void* map = NULL; D3D12_RANGE none = {0, 0};
    ID3D12Resource_Map(bin, 0, &none, &map); memcpy(map, raw, (size_t)fsz); ID3D12Resource_Unmap(bin, 0, NULL);
    /* commands */
    D3D12_COMMAND_QUEUE_DESC qd = {0}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue* q = NULL; ID3D12CommandAllocator* al = NULL; ID3D12GraphicsCommandList* cl = NULL;
    ID3D12Device_CreateCommandQueue(dev, &qd, &IID_ID3D12CommandQueue, (void**)&q);
    ID3D12Device_CreateCommandAllocator(dev, D3D12_COMMAND_LIST_TYPE_DIRECT, &IID_ID3D12CommandAllocator, (void**)&al);
    ID3D12Device_CreateCommandList(dev, 0, D3D12_COMMAND_LIST_TYPE_DIRECT, al, pso, &IID_ID3D12GraphicsCommandList, (void**)&cl);
    ID3D12GraphicsCommandList_SetComputeRootSignature(cl, rs);
    ID3D12GraphicsCommandList_SetPipelineState(cl, pso);
    ID3D12GraphicsCommandList_SetComputeRootShaderResourceView(cl, 1, ID3D12Resource_GetGPUVirtualAddress(bin));
    ID3D12GraphicsCommandList_SetComputeRootUnorderedAccessView(cl, 2, ID3D12Resource_GetGPUVirtualAddress(bout));
    for (size_t i = 0; i < n; i++) {
        const UINT k[8] = { cs[i].slot, cs[i].nq, cs[i].in_off, cs[i].in_off + 32u * cs[i].nq, cs[i].out_off, 0, 0, 0 };
        ID3D12GraphicsCommandList_SetComputeRoot32BitConstants(cl, 0, 8, k, 0);
        ID3D12GraphicsCommandList_Dispatch(cl, (cs[i].nq + 63u) / 64u, 1, 1);
    }
    D3D12_RESOURCE_BARRIER b = {0};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; b.Transition.pResource = bout;
    b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS; b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    ID3D12GraphicsCommandList_ResourceBarrier(cl, 1, &b);
    ID3D12GraphicsCommandList_CopyBufferRegion(cl, brb, 0, bout, 0, out_size);
    ID3D12GraphicsCommandList_Close(cl);
    ID3D12CommandList* lists[1] = { (ID3D12CommandList*)cl };
    ID3D12CommandQueue_ExecuteCommandLists(q, 1, lists);
    ID3D12Fence* fe = NULL; ID3D12Device_CreateFence(dev, 0, D3D12_FENCE_FLAG_NONE, &IID_ID3D12Fence, (void**)&fe);
    HANDLE ev = CreateEventA(NULL, FALSE, FALSE, NULL);
    ID3D12CommandQueue_Signal(q, fe, 1);
    ID3D12Fence_SetEventOnCompletion(fe, 1, ev);
    WaitForSingleObject(ev, 30000);
    if (ID3D12Fence_GetCompletedValue(fe) != 1) { printf("T gpu timeout\n"); return 3; }
    const uint8_t* got = NULL; D3D12_RANGE rr = {0, (SIZE_T)out_size};
    ID3D12Resource_Map(brb, 0, &rr, (void**)&got);
    size_t ok = 0, bad = 0, per[2][2] = {{0, 0}, {0, 0}};
    for (size_t i = 0; i < n; i++) {
        const uint8_t* want = raw + cs[i].in_off + 64u * cs[i].nq;
        const int s = cs[i].slot == 72;
        if (!memcmp(got + cs[i].out_off, want, 16u * cs[i].nq)) { ok++; per[s][0]++; continue; }
        bad++; per[s][1]++;
        if (bad <= 5) {
            uint32_t a = 0;
            while (a < 16u * cs[i].nq && got[cs[i].out_off + a] == want[a]) a++;
            printf("C case %zu slot %u nq %u MISMATCH at byte %u: gpu %02X lifted %02X\n", i, cs[i].slot, cs[i].nq, a,
                   got[cs[i].out_off + a], want[a]);
        }
    }
    printf("T gpu cases=%zu match=%zu mismatch=%zu (slot 71 %zu/%zu, slot 72 %zu/%zu) bytes=%zu adapter=%s%s\n", n, ok, bad,
           per[0][0], per[0][0] + per[0][1], per[1][0], per[1][0] + per[1][1], out_total, adapter, mutate ? " mutate" : "");
    fflush(stdout);
    return bad ? 1 : 0;
}
