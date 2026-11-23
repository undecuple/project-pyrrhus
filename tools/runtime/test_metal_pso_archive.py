#!/usr/bin/env python3
"""The MTLBinaryArchive flow the Metal pipeline cache (its patch 2173) relies on.

No toolkit, game files or display needed; macOS and a GPU device required (like the
Metal smoke tests). Compiles one small harness that walks the archive sequence:

    miss  -> a create with MTLPipelineOptionFailOnBinaryArchiveMiss fails on a miss
    build -> the plain create succeeds
    add   -> addRenderPipelineFunctionsWithDescriptor records the functions
    write -> serializeToURL writes a non-empty file
    load  -> a fresh archive opens from that file
    hit   -> the same descriptor now creates with the fail-on-miss option

Prints PASS lines and exits non-zero on the first step that does not hold.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

SOURCE = r'''
#import <Metal/Metal.h>
#include <stdio.h>

static NSString* const kMsl = @""
    "#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "struct vs_out { float4 p [[position]]; };\n"
    "vertex vs_out vs_main(uint vid [[vertex_id]]) {\n"
    "    return { float4((vid == 1) ? 3.f : -1.f, (vid == 2) ? 3.f : -1.f, 0.f, 1.f) };\n"
    "}\n"
    "fragment float4 fs_main() { return float4(0.25f, 0.5f, 0.75f, 1.f); }\n";

static MTLRenderPipelineDescriptor* make_pd(id<MTLDevice> dev, id<MTLLibrary> lib)
{
    MTLRenderPipelineDescriptor* pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction   = [lib newFunctionWithName:@"vs_main"];
    pd.fragmentFunction = [lib newFunctionWithName:@"fs_main"];
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    return pd;
}

int main(int argc, char** argv)
{
    if (argc != 2) return 64;
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) { puts("FAIL: no Metal device"); return 1; }
        NSError* err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:kMsl options:nil error:&err];
        if (!lib) { printf("FAIL: library: %s\n", [[err localizedDescription] UTF8String]); return 1; }

        NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
        MTLBinaryArchiveDescriptor* ad = [MTLBinaryArchiveDescriptor new];
        ad.url = url;
        id<MTLBinaryArchive> arch = [dev newBinaryArchiveWithDescriptor:ad error:&err];
        if (arch) { puts("FAIL: an archive opened from a file that does not exist"); return 1; }
        puts("PASS: no file, no archive (the cache starts cold exactly like the game)");

        ad.url = nil;
        arch = [dev newBinaryArchiveWithDescriptor:ad error:&err];
        if (!arch) { printf("FAIL: empty archive: %s\n", [[err localizedDescription] UTF8String]); return 1; }
        puts("PASS: an empty archive is created");

        MTLRenderPipelineDescriptor* pd = make_pd(dev, lib);
        pd.binaryArchives = @[arch];
        id<MTLRenderPipelineState> pso =
            [dev newRenderPipelineStateWithDescriptor:pd
                                               options:MTLPipelineOptionFailOnBinaryArchiveMiss
                                            reflection:NULL error:&err];
        if (pso) { puts("FAIL: the miss probe succeeded on an empty archive"); return 1; }
        puts("PASS: fail-on-miss reports a cold pipeline");

        pso = [dev newRenderPipelineStateWithDescriptor:pd error:&err];
        pd.binaryArchives = nil;
        if (!pso) { printf("FAIL: plain create: %s\n", [[err localizedDescription] UTF8String]); return 1; }
        puts("PASS: the plain build succeeds");

        if (![arch addRenderPipelineFunctionsWithDescriptor:pd error:&err]) {
            printf("FAIL: add functions: %s\n", [[err localizedDescription] UTF8String]);
            return 1;
        }
        puts("PASS: the functions are recorded in the archive");

        if (![arch serializeToURL:url error:&err]) {
            printf("FAIL: serialize: %s\n", [[err localizedDescription] UTF8String]);
            return 1;
        }
        NSDictionary* attrs = [[NSFileManager defaultManager]
            attributesOfItemAtPath:[NSString stringWithUTF8String:argv[1]] error:NULL];
        if (![attrs fileSize]) { puts("FAIL: the archive file is empty"); return 1; }
        printf("PASS: %llu bytes written to disk\n", (unsigned long long)[attrs fileSize]);

        MTLBinaryArchiveDescriptor* rd = [MTLBinaryArchiveDescriptor new];
        rd.url = url;
        id<MTLBinaryArchive> loaded = [dev newBinaryArchiveWithDescriptor:rd error:&err];
        if (!loaded) { printf("FAIL: reload: %s\n", [[err localizedDescription] UTF8String]); return 1; }
        puts("PASS: the archive opens again from the file");

        MTLRenderPipelineDescriptor* pd2 = make_pd(dev, lib);
        pd2.binaryArchives = @[loaded];
        id<MTLRenderPipelineState> pso2 =
            [dev newRenderPipelineStateWithDescriptor:pd2
                                               options:MTLPipelineOptionFailOnBinaryArchiveMiss
                                            reflection:NULL error:&err];
        if (!pso2) { printf("FAIL: the hit probe: %s\n", [[err localizedDescription] UTF8String]); return 1; }
        puts("PASS: the second run creates the pipeline straight from the archive");
        return 0;
    }
}
'''


def main():
    if sys.platform != 'darwin':
        raise SystemExit('The MTLBinaryArchive flow test requires macOS')
    with tempfile.TemporaryDirectory(prefix='kz2-pso-archive.') as tmp:
        src = Path(tmp) / 'pso_archive_test.m'
        bin_ = Path(tmp) / 'pso_archive_test'
        archive = Path(tmp) / 'metal-pso.bin'
        src.write_text(SOURCE)
        build = subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-framework', 'Metal',
                                '-framework', 'Foundation', str(src), '-o', str(bin_)],
                               capture_output=True, text=True)
        if build.returncode:
            print(build.stderr)
            raise SystemExit('The test harness did not compile')
        run = subprocess.run([str(bin_), str(archive)], capture_output=True, text=True)
        print(run.stdout, end='')
        if run.returncode != 0:
            print(run.stderr, end='')
            raise SystemExit(f'The MTLBinaryArchive flow broke (exit {run.returncode})')
        print('OK: the archive flow the Metal pipeline cache uses holds end to end')


if __name__ == '__main__':
    main()
