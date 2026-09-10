import { createRoot } from 'react-dom/client';
import {useState} from 'react';
import './index.css';
import Header from './components/Header';
import Footer from './components/Footer';
import {post} from './lib/api';
import News from './pages/News';

export default function App(){
 const [refreshing,setRefreshing]=useState(false);
 async function refresh(){setRefreshing(true);try{await post('/refresh');location.reload()}finally{setRefreshing(false)}}
 return <div className="min-h-screen bg-slate-50"><Header refreshing={refreshing} onRefresh={refresh}/><News egypt/><Footer/></div>
}
createRoot(document.getElementById('root')).render(<App />);
