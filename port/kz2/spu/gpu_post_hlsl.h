/* gpu_post_hlsl.h -- HLSL compute kernels for the SPU post chain on the GPU (D52's GPU compute passes,
 * D46: bit-exact, env-flagged). One source for the walker's passes and the harness (tools/spu/gpu_post_test.c), compiled
 * with D3DCompile cs_5_0. Each kernel is the integer formula of the lifted SPU code, byte for byte on guest memory
 * layouts (a ByteAddressBuffer holds the guest bytes as they are: words load little-endian, so byte-wise operations
 * are layout-independent and big-endian halfwords are assembled from their bytes).
 *
 * Kernel 1 (kind 71): Gfx.Post.Downsample's RGBA8 row kernel @0x5620 (job_00d50280; native_postjobs.c down4_5620).
 *   Output quadword j (4 pixels) from source quadwords Q0, Q1 (row 0 at 32 j, 32 j + 16) and R0, R1 (row 1):
 *   t1 = avgb(Q0, R0), t2 = avgb(Q1, R1), out = avgb(words 0, 2 of t1 and t2, words 1, 3 of t1 and t2), avgb the
 *   SPU's rounding byte average (a + b + 1) >> 1.
 * Kernel 2 (kind 72): its 16-bit row kernel @0x56D0 (down8_56D0): per row, with big-endian halfword channels c of
 *   the row's quadwords q0 (pixels 0, 1) and q1 (pixels 2, 3): h0 = (q0[c] + q1[c]) >> 1, h1 = (q0[4 + c] + q1[4 + c])
 *   >> 1, r = (h0 + h1) >> 1; output quadword j = row 0's r (4 big-endian halfwords) then row 1's.
 * Thread j of a dispatch computes output quadword j; constants: kind, nq (output quadwords), the byte offsets of
 * source row 0, source row 1 and the output in their buffers. KZ2_GPU_POST_MUTATE (harness only) swaps in a
 * truncating byte average (kind 71) and a rounding halfword average (kind 72), which the harness must catch. */
#ifndef KZ2_GPU_POST_HLSL_H
#define KZ2_GPU_POST_HLSL_H
static const char kz2_gpu_post_hlsl[] =
"ByteAddressBuffer src : register(t0);\n"
"RWByteAddressBuffer dst : register(u0);\n"
"cbuffer K : register(b0) { uint kind; uint nq; uint off0; uint off1; uint offo; uint k5; uint k6; uint k7; };\n"
"uint avgb(uint a, uint b)\n"
"{\n"
"#ifdef KZ2_GPU_POST_MUTATE\n"
"    return (a & b) + (((a ^ b) >> 1) & 0x7F7F7F7Fu);\n"
"#else\n"
"    return (a | b) - (((a ^ b) >> 1) & 0x7F7F7F7Fu);\n"
"#endif\n"
"}\n"
"uint byte_at(uint o) { return (src.Load(o & ~3u) >> ((o & 3u) * 8u)) & 0xFFu; }\n"
"uint hw_be(uint o) { return (byte_at(o) << 8) | byte_at(o + 1u); }\n"
"uint4 ds8_row(uint q)\n"
"{\n"
"    uint4 r;\n"
"    [unroll] for (uint c = 0; c < 4; c++) {\n"
"        uint h0 = (hw_be(q + 2u * c) + hw_be(q + 16u + 2u * c)) >> 1;\n"
"        uint h1 = (hw_be(q + 8u + 2u * c) + hw_be(q + 24u + 2u * c)) >> 1;\n"
"#ifdef KZ2_GPU_POST_MUTATE\n"
"        r[c] = (h0 + h1 + 1u) >> 1;\n"
"#else\n"
"        r[c] = (h0 + h1) >> 1;\n"
"#endif\n"
"    }\n"
"    return r;\n"
"}\n"
"uint pack_be(uint a, uint b) { return ((a >> 8) & 0xFFu) | ((a & 0xFFu) << 8) | (((b >> 8) & 0xFFu) << 16) | ((b & 0xFFu) << 24); }\n"
"[numthreads(64, 1, 1)]\n"
"void main(uint3 id : SV_DispatchThreadID)\n"
"{\n"
"    uint j = id.x;\n"
"    if (j >= nq) return;\n"
"    if (kind == 71u) {\n"
"        uint4 q0 = src.Load4(off0 + 32u * j), q1 = src.Load4(off0 + 32u * j + 16u);\n"
"        uint4 r0 = src.Load4(off1 + 32u * j), r1 = src.Load4(off1 + 32u * j + 16u);\n"
"        uint4 t1, t2;\n"
"        [unroll] for (uint w = 0; w < 4; w++) { t1[w] = avgb(q0[w], r0[w]); t2[w] = avgb(q1[w], r1[w]); }\n"
"        uint4 ev = uint4(t1.x, t1.z, t2.x, t2.z), od = uint4(t1.y, t1.w, t2.y, t2.w), o;\n"
"        [unroll] for (uint k = 0; k < 4; k++) o[k] = avgb(ev[k], od[k]);\n"
"        dst.Store4(offo + 16u * j, o);\n"
"    } else if (kind == 72u) {\n"
"        uint4 a = ds8_row(off0 + 32u * j), b = ds8_row(off1 + 32u * j);\n"
"        dst.Store4(offo + 16u * j, uint4(pack_be(a.x, a.y), pack_be(a.z, a.w), pack_be(b.x, b.y), pack_be(b.z, b.w)));\n"
"    }\n"
"}\n";
#endif
