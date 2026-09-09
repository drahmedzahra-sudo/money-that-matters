const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
export async function get(path){const r=await fetch(API+path); if(!r.ok) throw new Error(await r.text()); return r.json()}
export async function post(path){const r=await fetch(API+path,{method:'POST'}); if(!r.ok) throw new Error(await r.text()); return r.json()}
