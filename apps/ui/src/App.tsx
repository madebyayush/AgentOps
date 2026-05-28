import React, { useState, useEffect } from 'react';
import { 
  Activity, 
  Cpu, 
  Database, 
  ShieldCheck, 
  Play, 
  Terminal, 
  Layers, 
  Compass, 
  Key, 
  Server,
  Code2,
  CheckCircle2,
  Workflow
} from 'lucide-react';

function App() {
  const [pipelineState, setPipelineState] = useState<'idle' | 'running' | 'completed'>('idle');
  const [executionLogs, setExecutionLogs] = useState<string[]>([
    '[system] AgentOps core operational. System idle.'
  ]);
  const [systemLoad, setSystemLoad] = useState({ cpu: 12, memory: 34, network: 0.1 });

  // Simulate metrics updating
  useEffect(() => {
    const interval = setInterval(() => {
      setSystemLoad(prev => ({
        cpu: Math.min(99, Math.max(8, prev.cpu + (Math.random() * 6 - 3))),
        memory: Math.min(99, Math.max(30, prev.memory + (Math.random() * 2 - 1))),
        network: Math.min(100, Math.max(0.1, prev.network + (Math.random() * 2 - 1)))
      }));
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const runSamplePipeline = () => {
    if (pipelineState === 'running') return;
    
    setPipelineState('running');
    setExecutionLogs([
      '[gateway] Intercepting request: "Evaluate quarterly financial targets & fetch market reports"',
      '[security] PII redaction and risk scoring complete. Clearance: PASS.',
      '[router] Selecting execution engine: cognitive-core-alpha',
      '[memory] Pulling long-term user preferences from semantic index (Qdrant)...',
      '[memory] Context injected. Generating task graph...'
    ]);

    setTimeout(() => {
      setExecutionLogs(prev => [
        ...prev,
        '[runtime] Task 1/3: Launching web researcher subagent to gather competitor metrics.',
        '[researcher] Fetching data via ChEMBL API & Literature databases...',
        '[researcher] 24 target files crawled. Extracted performance structures.'
      ]);
    }, 1500);

    setTimeout(() => {
      setExecutionLogs(prev => [
        ...prev,
        '[runtime] Task 2/3: Synthesizing metrics inside memory adapter (Redis cache).',
        '[security] Verifying target values against compliance schemas...',
        '[observability] Traced subagent execution path to Jaeger. Span ID: e98f12a.'
      ]);
    }, 3000);

    setTimeout(() => {
      setExecutionLogs(prev => [
        ...prev,
        '[runtime] Task 3/3: Pushing consolidated report payload to MinIO storage.',
        '[gateway] Orchestration completed successfully. Notification dispatched via Slack hook.',
        '[system] Status: IDLE. Ready for instructions.'
      ]);
      setPipelineState('completed');
    }, 4500);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans grid-bg relative overflow-hidden">
      {/* Decorative Glow Elements */}
      <div className="glow-bg glow-violet" />
      <div className="glow-bg glow-cyan" />

      {/* TOP HEADER */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-violet-600 to-cyan-500 flex items-center justify-center shadow-lg shadow-violet-500/20">
              <Workflow className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-100 to-slate-400">
                AgentOps
              </h1>
              <p className="text-[10px] text-violet-400 font-mono tracking-widest uppercase">
                Autonomous OS
              </p>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-400">
              <a href="#" className="hover:text-slate-100 transition-colors">Dashboard</a>
              <a href="#" className="hover:text-slate-100 transition-colors">Workspaces</a>
              <a href="#" className="hover:text-slate-100 transition-colors">Observability</a>
              <a href="#" className="hover:text-slate-100 transition-colors">Toolbox</a>
            </nav>
            <span className="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              SYSTEM HEALTHY
            </span>
          </div>
        </div>
      </header>

      {/* MAIN CONTAINER */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* LEFT COLUMN: CONTROL ROOM */}
        <section className="lg:col-span-2 space-y-8">
          {/* WELCOME BANNER */}
          <div className="glass-panel p-8 relative overflow-hidden">
            <div className="relative z-10">
              <h2 className="text-3xl font-extrabold text-white mb-2 font-heading">
                Enterprise workflow, solved autonomously.
              </h2>
              <p className="text-slate-400 text-sm max-w-xl leading-relaxed mb-6">
                AgentOps orchestrates multi-agent operations, persistent knowledge graphs, 
                and high-security system logic to build stable, self-improving automation structures.
              </p>
              <div className="flex flex-wrap gap-4">
                <button 
                  onClick={runSamplePipeline}
                  disabled={pipelineState === 'running'}
                  className="btn-primary flex items-center gap-2"
                >
                  <Play className={`h-4 w-4 ${pipelineState === 'running' ? 'animate-spin' : ''}`} />
                  {pipelineState === 'running' ? 'Executing Plan...' : 'Trigger Agent Run'}
                </button>
                <button className="btn-secondary flex items-center gap-2">
                  <Code2 className="h-4 w-4" />
                  View Registered Tools
                </button>
              </div>
            </div>
            {/* Absolute accent */}
            <div className="absolute right-0 bottom-0 top-0 w-1/3 bg-gradient-to-l from-violet-500/10 to-transparent pointer-events-none" />
          </div>

          {/* ACTIVE EXECUTION PIPELINE SCREEN */}
          <div className="glass-panel p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-2">
                <Terminal className="h-5 w-5 text-cyan-400" />
                <h3 className="font-heading font-semibold text-white">Live Execution Terminal</h3>
              </div>
              <span className="font-mono text-xs text-slate-500">task_ref: ops_8897_cba</span>
            </div>
            
            <div className="bg-slate-950/80 rounded-lg p-4 font-mono text-xs text-slate-300 h-64 overflow-y-auto space-y-2 border border-slate-900">
              {executionLogs.map((log, index) => (
                <div key={index} className="flex gap-2">
                  <span className="text-slate-600">[{index + 1}]</span>
                  <span className={log.includes('[system]') ? 'text-violet-400' : log.includes('[security]') ? 'text-emerald-400 font-semibold' : log.includes('[researcher]') ? 'text-cyan-400' : 'text-slate-300'}>
                    {log}
                  </span>
                </div>
              ))}
              {pipelineState === 'running' && (
                <div className="flex items-center gap-2 text-cyan-400 animate-pulse">
                  <span>&gt;</span>
                  <span>Agent is reasoning...</span>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN: INFRA & TELEMETRY MODULE */}
        <section className="space-y-8">
          
          {/* STATS PANEL */}
          <div className="glass-panel p-6 space-y-6">
            <h3 className="font-heading font-semibold text-white border-b border-slate-800 pb-4 flex items-center gap-2">
              <Activity className="h-5 w-5 text-violet-400" />
              Runtime Telemetry
            </h3>
            
            <div className="space-y-4">
              {/* CPU */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-slate-400"><Cpu className="h-3 w.5" /> Dynamic CPU Load</span>
                  <span className="text-white font-medium">{systemLoad.cpu.toFixed(1)}%</span>
                </div>
                <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                  <div 
                    className="h-full bg-gradient-to-r from-violet-600 to-cyan-400 transition-all duration-1000"
                    style={{ width: `${systemLoad.cpu}%` }}
                  />
                </div>
              </div>

              {/* Memory */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-slate-400"><Database className="h-3 w.5" /> Episodic Buffer (Redis)</span>
                  <span className="text-white font-medium">{systemLoad.memory.toFixed(1)}%</span>
                </div>
                <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                  <div 
                    className="h-full bg-gradient-to-r from-cyan-400 to-violet-600 transition-all duration-1000"
                    style={{ width: `${systemLoad.memory}%` }}
                  />
                </div>
              </div>

              {/* Network */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-slate-400"><Server className="h-3 w.5" /> Event Queue (Kafka)</span>
                  <span className="text-white font-medium">{systemLoad.network.toFixed(1)} req/s</span>
                </div>
                <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800">
                  <div 
                    className="h-full bg-violet-500 transition-all duration-1000"
                    style={{ width: `${Math.min(100, systemLoad.network * 15)}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* MONOREPO TOPOLOGY COMPONENT */}
          <div className="glass-panel p-6 space-y-4">
            <h3 className="font-heading font-semibold text-white border-b border-slate-800 pb-4 flex items-center gap-2">
              <Layers className="h-5 w-5 text-cyan-400" />
              Monorepo Architecture
            </h3>
            
            <div className="space-y-2 text-xs font-mono text-slate-300">
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800/80">
                <span className="text-slate-100 font-semibold">apps/ui</span>
                <span className="text-violet-400 uppercase text-[9px] px-2 py-0.5 rounded bg-violet-950/40 border border-violet-800/30">React+Vite</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800/80">
                <span className="text-slate-100 font-semibold">apps/api-gateway</span>
                <span className="text-cyan-400 uppercase text-[9px] px-2 py-0.5 rounded bg-cyan-950/40 border border-cyan-800/30">FastAPI</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800/80">
                <span className="text-slate-100 font-semibold">apps/agent-runtime</span>
                <span className="text-yellow-400 uppercase text-[9px] px-2 py-0.5 rounded bg-yellow-950/40 border border-yellow-800/30">Async Python</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800/80">
                <span className="text-slate-400">packages/*</span>
                <span className="text-slate-400 text-[9px] uppercase">5 Shared Libs</span>
              </div>
            </div>
          </div>

          {/* CORE PLATFORM POLICIES */}
          <div className="glass-panel p-6 space-y-4">
            <h3 className="font-heading font-semibold text-white border-b border-slate-800 pb-4 flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-400" />
              Autonomous Guardrails
            </h3>
            
            <ul className="space-y-2 text-xs text-slate-400">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                <span>Zero-Trust API clearance & context sandboxing.</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                <span>Dynamic PII redaction layer scanning outputs in real-time.</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                <span>Fail-safe fallbacks referencing AWS Bedrock endpoints.</span>
              </li>
            </ul>
          </div>

        </section>

      </main>

      {/* FOOTER */}
      <footer className="border-t border-slate-900 bg-slate-950 py-6 mt-12 text-center text-xs text-slate-500">
        <p>&copy; 2026 AgentOps Orchestration Platform. Principal Architect Dashboard.</p>
      </footer>
    </div>
  );
}

export default App;
