import {useEffect,useState} from 'react';
import {get} from '../lib/api';
import Card from '../components/Card';
import FeedState from '../components/FeedState';

export default function Match({watchlist,setWatchlist}){
 const [data,setData]=useState({items:[]}),[loading,setLoading]=useState(true),[selected,setSelected]=useState(null);
 useEffect(()=>{get('/matches').then(setData).catch(()=>{}).finally(()=>setLoading(false))},[]);
 if(loading)return <main className="mx-auto max-w-xl px-4 py-5"><div className="h-8 w-40 animate-pulse rounded bg-slate-200"/><div className="mt-5 h-32 animate-pulse rounded-2xl bg-slate-200"/></main>;
 return <main className="mx-auto max-w-xl px-4 py-5 pb-24">
  <h1 className="text-2xl font-semibold">Money Match</h1>
  <p className="mb-4 mt-1 text-sm text-slate-500">Where fresh public signals agree. Stale feeds are shown but excluded from scoring.</p>
  <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4 text-xs text-slate-600">Congress is filing-level in the free public path, so ticker-level Congress agreement is unavailable. A Strong Match requires three fresh ticker-level sources.</div>
  <div className="space-y-3">{data.items.map(x=><Card key={x.ticker} onClick={()=>setSelected(x.ticker)}>
   <div className="flex items-center justify-between"><div><div className="mono text-lg font-bold">{x.ticker}</div><div className="text-sm text-slate-500">{x.company||'Company name unavailable'}</div></div><button aria-label="Watchlist" onClick={e=>{e.stopPropagation();setWatchlist(x.ticker)}} className="text-xl">{watchlist.has(x.ticker)?'★':'☆'}</button></div>
   <div className="mt-4 flex items-end justify-between"><div><div className="mono text-4xl font-bold">{x.score}</div><div className={`text-sm font-medium ${x.direction==='bullish'?'text-green-600':x.direction==='bearish'?'text-red-600':'text-slate-500'}`}>{x.direction}</div></div><div className="text-right text-xs text-slate-500">{x.fired_sources.length?x.fired_sources.join(' · '):'No fresh signal'}{x.strong_match&&<div className="mt-1 font-semibold text-slate-800">⚡ Strong Match</div>}{x.stale_sources.length>0&&<div className="mt-1">Excluded stale: {x.stale_sources.join(', ')}</div>}</div></div>
  </Card>)}</div>
  {!data.items.length&&<div className="rounded-2xl border border-dashed p-8 text-center text-sm text-slate-500">Waiting for verified market or insider data. No demo records are used.</div>}
  {selected&&<TickerDetail ticker={selected} close={()=>setSelected(null)}/>}
 </main>
}

function TickerDetail({ticker,close}){const [d,setD]=useState(null);useEffect(()=>{get('/ticker/'+ticker).then(setD).catch(()=>{})},[ticker]);return <div className="fixed inset-0 z-50 bg-slate-900/20 p-3 backdrop-blur-sm"><div className="mx-auto mt-8 max-h-[82vh] max-w-xl overflow-auto rounded-3xl bg-white p-5 shadow-xl"><div className="flex items-center justify-between"><div><div className="mono text-xl font-bold">{ticker}</div><div className="text-sm text-slate-500">Signal detail</div></div><button onClick={close} className="rounded-full border px-3 py-1 text-sm">Close</button></div>{!d?<div className="py-10 text-center text-sm text-slate-500">Loading verified records...</div>:<><section className="mt-5"><h2 className="font-semibold">Market News</h2><div className="mt-2 space-y-2">{d.news.map(x=><a key={x.id} href={x.source_url} target="_blank" rel="noreferrer" className="block rounded-xl border p-3"><div className="text-sm font-medium">{x.headline}</div><div className="mt-1 text-xs text-slate-500">{x.outlet} · {x.published_at}</div></a>)}{!d.news.length&&<p className="text-xs text-slate-500">No verified ticker-specific news.</p>}</div></section><section className="mt-5"><h2 className="font-semibold">Insiders</h2><div className="mt-2 space-y-2">{d.insiders.map(x=><a key={x.id} href={x.source_url} target="_blank" rel="noreferrer" className="block rounded-xl border p-3"><div className="text-sm font-medium">{x.insider_name} · {x.action}</div><div className="mt-1 text-xs text-slate-500">{x.role||'Role unavailable'} · {x.filing_date}</div></a>)}{!d.insiders.length&&<p className="text-xs text-slate-500">No verified Form 4 transactions.</p>}</div></section><section className="mt-5 rounded-xl border border-slate-200 p-3 text-xs text-slate-600">{d.note}</section></>}</div></div>}
