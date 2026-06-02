import { useEffect, useState } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis
} from 'recharts';
import { Activity, Database, Zap, HardDrive } from 'lucide-react';

function Dashboard() {
  const [metrics, setMetrics] = useState([]);
  const [scores, setScores] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [metricsRes, scoresRes] = await Promise.all([
          fetch('/api/analytics/metrics'),
          fetch('/api/analytics/scores')
        ]);
        
        const metricsData = await metricsRes.json();
        const scoresData = await scoresRes.json();
        
        setMetrics(metricsData.data || []);
        setScores(scoresData);
      } catch (error) {
        console.error("Error fetching data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-purple-500"></div>
      </div>
    );
  }

  // Process data for charts
  const poissonData = metrics.filter(m => m.distribution === 'poisson');
  const zipfData = metrics.filter(m => m.distribution === 'zipf');

  const hitRateData = poissonData.map((p, i) => {
    const z = zipfData[i] || {};
    return {
      name: `${p.policy} (${p.size})`,
      Poisson: parseFloat(p.hit_rate_percent || 0),
      Zipf: parseFloat(z.hit_rate_percent || 0)
    };
  });

  // Prepare scatter data for scores
  const scatterData = scores?.cosine_scores?.map((cos, i) => ({
    cosine: cos,
    rouge: scores.rouge_scores[i] || 0
  })) || [];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 p-8">
      <header className="mb-10">
        <h1 className="text-4xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">
          Yahoo Answers LLM Analytics
        </h1>
        <p className="text-slate-400 mt-2">Plataforma de Análisis de Preguntas (Parte 3)</p>
      </header>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl flex items-center gap-4">
          <div className="p-3 bg-blue-500/10 rounded-xl text-blue-400">
            <Activity size={28} />
          </div>
          <div>
            <p className="text-sm text-slate-400 font-medium">Total Experimentos</p>
            <h3 className="text-2xl font-bold text-white">{metrics.length}</h3>
          </div>
        </div>
        
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl flex items-center gap-4">
          <div className="p-3 bg-purple-500/10 rounded-xl text-purple-400">
            <Zap size={28} />
          </div>
          <div>
            <p className="text-sm text-slate-400 font-medium">Mejor Hit Rate (Zipf)</p>
            <h3 className="text-2xl font-bold text-white">
              {Math.max(...zipfData.map(d => parseFloat(d.hit_rate_percent || 0)))}%
            </h3>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl flex items-center gap-4">
          <div className="p-3 bg-cyan-500/10 rounded-xl text-cyan-400">
            <Database size={28} />
          </div>
          <div>
            <p className="text-sm text-slate-400 font-medium">Evaluaciones LLM</p>
            <h3 className="text-2xl font-bold text-white">{scores?.total_processed || 0}</h3>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl flex items-center gap-4">
          <div className="p-3 bg-emerald-500/10 rounded-xl text-emerald-400">
            <HardDrive size={28} />
          </div>
          <div>
            <p className="text-sm text-slate-400 font-medium">Top Pregunta Hits</p>
            <h3 className="text-2xl font-bold text-white">
              {scores?.top_accesses?.[0]?.count || 0}
            </h3>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        {/* Hit Rate Chart */}
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
          <h2 className="text-xl font-semibold mb-6 text-slate-100">Comparativa Hit Rate (Caché)</h2>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hitRateData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="name" stroke="#64748b" />
                <YAxis stroke="#64748b" />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px' }}
                  itemStyle={{ color: '#e2e8f0' }}
                />
                <Legend />
                <Bar dataKey="Poisson" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Zipf" fill="#22d3ee" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Semantic vs Lexical Similitude */}
        <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
          <h2 className="text-xl font-semibold mb-6 text-slate-100">Calidad LLM: Semántica vs Léxica</h2>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" dataKey="cosine" name="Similitud Coseno" stroke="#64748b" domain={[0, 1]} />
                <YAxis type="number" dataKey="rouge" name="ROUGE-L" stroke="#64748b" domain={[0, 1]} />
                <ZAxis type="number" range={[50, 50]} />
                <Tooltip 
                  cursor={{ strokeDasharray: '3 3' }}
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px' }}
                />
                <Scatter name="Evaluaciones" data={scatterData} fill="#f43f5e" opacity={0.6} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
