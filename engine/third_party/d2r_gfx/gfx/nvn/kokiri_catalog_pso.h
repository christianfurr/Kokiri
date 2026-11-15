/* Included after nvn_pso_skey.h. No copied or independently guessed GPU ABI. */
#pragma once
static int kcr_render_proof(NSString *name, NSDictionary *proof) {
    pso_skey sk;
    if (pso_skey_parse(name.UTF8String, &sk) || sk.merged || sk.fz || sk.vs_stage != 0 ||
        (sk.fs[0] && sk.fs_stage != 1) || sk.k.vs || sk.k.fs || sk.k.fsfn || (sk.k.a2c & ~1u)) return 0;
    if (strnlen(sk.vs, sizeof sk.vs) >= sizeof sk.vs || strnlen(sk.fs, sizeof sk.fs) >= sizeof sk.fs) return 0;
    return [proof[@"vs"] isEqual:@(sk.vs)] && [proof[@"fs"] isEqual:@(sk.fs)];
}
