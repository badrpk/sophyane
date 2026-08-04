from sophyane.native.fast_path import try_fast_path
for q in ['system configuration?', 'how many local llm models you have?', 'version', 'what model are you using?']:
    r = try_fast_path(q)
    print('Q:', q)
    print('A:', r.text if r else None, f'({r.latency_ms:.2f} ms)' if r else '')
    print('---')
