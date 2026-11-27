# Blackbox stubs for every macro without a timing model, except the ones
# STA must see through (tt_mux/tt_ctrl netlists, the SRAM and the SRAM tile
# from liberty).
import re, sys, glob, os
vd = sys.argv[1]
keep_out = {'tt_mux', 'tt_ctrl', 'SP6TSRAM256x32', 'tt_um_example_sram'}
out = []
for f in sorted(glob.glob(os.path.join(vd, '*.v'))):
    b = os.path.basename(f)
    if b.endswith('.nl.v') or b in ('tt_mux.v', 'tt_ctrl.v', 'SP6TSRAM256x32.v', 'tt_um_example_sram.v'):
        continue
    t = open(f).read()
    t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
    t = re.sub(r'//[^\n]*', '', t)
    for m in re.finditer(r'(\(\*\s*blackbox\s*\*\)\s*)?module\s+(\w+)\b.*?endmodule', t, re.S):
        if m.group(2) in keep_out:
            continue
        body = m.group(0)
        body = re.sub(r'`ifdef\s+USE_POWER_PINS.*?`endif', '', body, flags=re.S)
        body = re.sub(r'\(\*.*?\*\)', '', body, flags=re.S)
        k = body.find(');')
        hdr = body[:k + 2] if k >= 0 else body[:body.index(';') + 1]
        hdr = re.sub(r',(\s*\))', r'\1', hdr)   # trailing comma left by a removed block
        out.append(hdr + '\nendmodule')
open(sys.argv[2], 'w').write('\n\n'.join(out) + '\n')
print(len(out), 'stub modules')
