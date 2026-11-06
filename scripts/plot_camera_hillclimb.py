#!/usr/bin/env python3
"""Build a self-contained interactive report from an issue #520 study directory."""
import argparse
import csv
import json
from pathlib import Path


def render(directory):
    report = json.loads((directory / 'report.json').read_text())
    cases = []
    for run in report['runs']:
        if not run['name'].endswith('-1'):
            continue
        with (directory / (run['name'] + '.csv')).open() as stream:
            points = [[round(float(value), 6) for value in row.values()] for row in csv.DictReader(stream)]
        cases.append(dict(name=run['name'], kind=run['kind'], split=run['split'], points=points,
                          direct=run['direct']['rmse'], exp=run['exponential_55ms']['rmse'],
                          candidate=run['candidate']['rmse']))
    failed = [gate['name'] for gate in report['gates'] if not gate['passed']]
    data = json.dumps(dict(cases=cases, verdict=report['verdict'], winner=report['winner']['candidate'],
                           failed=failed, native_runs=len(report['runs'])), separators=(',', ':'))
    html = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{box-sizing:border-box}body{margin:0;color:var(--foreground);font-family:var(--font-sans)}p{line-height:1.5;margin:8px 0}.muted{color:var(--muted-foreground);font-size:13px}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0}select{max-width:100%;padding:8px;color:var(--foreground);background:var(--secondary);border:1px solid var(--border);border-radius:var(--radius)}svg{width:100%;height:320px;overflow:visible}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:13px}.legend span:before{content:"";display:inline-block;width:18px;border-top:3px solid var(--c);margin-right:5px;vertical-align:middle}table{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}th,td{padding:8px;text-align:right;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}th{color:var(--muted-foreground);font-weight:500}.scroll{overflow-x:auto}code{font-family:var(--font-mono);font-size:12px}.note{padding:16px;background:var(--card);border-radius:var(--radius);margin-top:12px}
</style></head><body><p><strong>Native Skyrim stair-camera response</strong> <span id="verdict" class="muted"></span></p><div class="controls"><label for="case">Trace</label><select id="case"></select><span id="split" class="muted"></span></div><div class="legend"><span style="--c:var(--foreground)">Skyrim</span><span style="--c:var(--chart-2)">55 ms exponential</span><span style="--c:var(--chart-1)">Fitted response</span><span style="--c:var(--chart-3)">Direct follow</span></div><svg id="plot" viewBox="0 0 720 320" role="img" aria-label="Camera height relative to the player over time"></svg><p class="muted">Camera height relative to the player, with the stationary eye offset removed. Units: Creation units. Time zero is native W press. Each replay uses that run’s actual player trajectory and native timestep.</p><div class="scroll"><table><thead><tr><th>Fixture (repeat 1)</th><th>Direct RMSE</th><th>55 ms RMSE</th><th>Fitted RMSE</th></tr></thead><tbody id="metrics"></tbody></table></div><div class="note"><p id="parameters"></p><p class="muted">The 55 ms curve uses PR #511’s response formula with all vertical deltas. Its solver eligibility is not replayed. The fitted response runs freely after initialization; native future spring state is not fed into it. Production defaults are unchanged.</p></div><script>
const data=__DATA__;
// Keep the exported file usable outside the host, without overriding host theme tokens.
const defaults={'--foreground':'#20242b','--muted-foreground':'#596575','--secondary':'#edf1f5','--border':'#d1d8e0','--card':'#f2f5f8','--chart-1':'#007d73','--chart-2':'#b75100','--chart-3':'#7356ba','--radius':'8px','--font-sans':'system-ui, sans-serif','--font-mono':'monospace'};
const root=document.documentElement,theme=getComputedStyle(root);
for(const [name,value] of Object.entries(defaults))if(!theme.getPropertyValue(name).trim())root.style.setProperty(name,value);
const select=document.getElementById('case');
data.cases.forEach((c,i)=>select.add(new Option(c.name,i)));
const firstFailure=data.cases.findIndex(c=>data.failed.some(g=>g.startsWith(c.name+':')));
const firstHeld=data.cases.findIndex(c=>c.split==='heldout');select.value=Math.max(firstFailure>=0?firstFailure:firstHeld,0);
document.getElementById('verdict').textContent=data.verdict.replaceAll('_',' ')+' · '+data.native_runs+' native runs evaluated';
document.getElementById('parameters').textContent=data.winner.model==='spring'?'Selected spring base = '+data.winner.a.toPrecision(6)+' · damping = '+data.winner.b.toPrecision(6):'Selected exponential time constant = '+(data.winner.a*1000).toPrecision(6)+' ms';
if(data.failed.length){const p=document.createElement('p');p.className='muted';p.textContent='Failed held-out gates: '+data.failed.join(', ')+'.';document.querySelector('.note').append(p);}
document.getElementById('metrics').innerHTML=data.cases.map(c=>`<tr><td>${c.name} (${c.split})</td><td>${c.direct.toFixed(4)}</td><td>${c.exp.toFixed(4)}</td><td>${c.candidate.toFixed(4)}</td></tr>`).join('');
function draw(){
 const c=data.cases[Number(select.value)],p=c.points;document.getElementById('split').textContent=c.split==='heldout'?'Held out from parameter search':'Training fixture';
 const x0=p[0][0],x1=p.at(-1)[0],all=p.flatMap(q=>[q[2],q[3],q[4],q[5]]);let lo=Math.min(...all),hi=Math.max(...all);let pad=Math.max((hi-lo)*.12,.01);lo-=pad;hi+=pad;
 const X=x=>54+(x-x0)/(x1-x0)*648,Y=y=>274-(y-lo)/(hi-lo)*242;
 let svg='';
 for(let i=0;i<=5;i++){let y=lo+(hi-lo)*i/5;svg+=`<line x1="54" x2="702" y1="${Y(y)}" y2="${Y(y)}" stroke="var(--border)"/><text x="46" y="${Y(y)+4}" text-anchor="end" fill="var(--muted-foreground)" font-size="11">${y.toFixed(Math.abs(hi-lo)<1?3:1)}</text>`;}
 for(let i=0;i<=5;i++){let x=x0+(x1-x0)*i/5;svg+=`<text x="${X(x)}" y="294" text-anchor="middle" fill="var(--muted-foreground)" font-size="11">${x.toFixed(1)} s</text>`;}
 if(x0<=0)svg+=`<line x1="${X(0)}" x2="${X(0)}" y1="32" y2="274" stroke="var(--muted-foreground)" stroke-dasharray="4 4"/>`;
 for(const [column,color,width] of [[3,'var(--chart-3)',1.5],[4,'var(--chart-2)',2],[2,'var(--foreground)',3],[5,'var(--chart-1)',1.8]]){let path=p.map((q,i)=>(i?'L':'M')+X(q[0]).toFixed(2)+','+Y(q[column]).toFixed(2)).join(' ');svg+=`<path d="${path}" fill="none" stroke="${color}" stroke-width="${width}"/>`;}
 document.getElementById('plot').innerHTML=svg;
}
select.addEventListener('change',draw);draw();
</script></body></html>'''.replace('__DATA__', data)
    path = directory / 'report.html'
    path.write_text(html)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(render(args.directory.resolve()))
