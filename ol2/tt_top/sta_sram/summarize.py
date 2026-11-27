import sys, re, collections
f=sys.argv[1]; t=open(f).read()
for mode in ('max','min'):
    sec=t.split(f'=== ALLEND {mode}')[1].split('=== ALLEND')[0] if f'=== ALLEND {mode}' in t else ''
    c=collections.defaultdict(list)
    for line in sec.splitlines():
        m=re.match(r'^(\S+) \((\S+)\)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+) \((\w+)\)', line)
        if not m: continue
        ep,cell,req,act,sl,st=m.groups(); sl=float(sl)
        if 'tt_um_I/sram_rdata' in ep: k='tile <- SRAM read data'
        elif 'tt_um_I/' in ep: k='tile other '+ep.split('/')[-1].split('[')[0]
        elif re.search(r'sram_(lo|hi)_I/a', ep): k='SRAM addr pin'
        elif re.search(r'sram_(lo|hi)_I/', ep): k='SRAM d/we pin'
        else: k='tt_top flop '+cell
        c[k].append(sl)
    print('==', mode)
    for k,v in sorted(c.items(), key=lambda kv: min(kv[1])):
        print(f'  {k:45s} n={len(v):4d} worst={min(v):8.2f} failing={sum(1 for x in v if x<0)}')
