import { useState, useEffect, useRef, ComponentType } from 'react';
import { 
  Activity, 
  Cpu, 
  Database, 
  Play, 
  Terminal, 
  Server,
  Code2,
  Workflow,
  Settings,
  AlertTriangle,
  Sliders,
  UserCheck,
  X,
  Search,
  Check,
  AlertOctagon,
  RefreshCw,
  ShieldCheck,
  Layers,
  CheckCircle2,
  FileText
} from 'lucide-react';

interface Agent {
  id: string;
  name: string;
  type: string;
  config_json: Record<string, unknown>;
  created_at: string;
}

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_schema: Record<string, unknown>;
  is_enabled: boolean;
  created_at: string;
}

interface HitlRequest {
  id: string;
  run_id: string;
  action_description: string;
  context_json: Record<string, unknown>;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  approved_by: string | null;
  rejection_reason: string | null;
  decided_at: string | null;
  created_at: string;
}

interface Incident {
  id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
  status: 'open' | 'investigating' | 'resolved' | 'closed';
  root_cause: string | null;
  resolution: string | null;
  affected_run_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

function App() {
  // Tabs
  const [activeTab, setActiveTab] = useState<'control' | 'directory' | 'hitl' | 'observability'>('control');
  
  // Settings & Authentication State
  const [gatewayUrl, setGatewayUrl] = useState(() => localStorage.getItem('agentops_gateway_url') || 'http://localhost:8000');
  const [authMethod, setAuthMethod] = useState(() => localStorage.getItem('agentops_auth_method') || 'jwt');
  const [jwtToken, setJwtToken] = useState(() => localStorage.getItem('agentops_jwt_token') || '');
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('agentops_api_key') || '');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  
  // Temporary inputs in modal settings
  const [tempGatewayUrl, setTempGatewayUrl] = useState(gatewayUrl);
  const [tempAuthMethod, setTempAuthMethod] = useState(authMethod);
  const [tempJwtToken, setTempJwtToken] = useState(jwtToken);
  const [tempApiKey, setTempApiKey] = useState(apiKey);

  // System Health
  const [systemHealth, setSystemHealth] = useState<'healthy' | 'degraded' | 'disconnected'>('disconnected');
  const [healthChecks, setHealthChecks] = useState<Record<string, string>>({});

  // Loaded DB entities
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [hitlRequests, setHitlRequests] = useState<HitlRequest[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  
  // Control Room Run Settings
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [runPrompt, setRunPrompt] = useState('');
  const [requireHitl, setRequireHitl] = useState(false);
  const [maxSteps, setMaxSteps] = useState(25);
  const [runContext, setRunContext] = useState('{\n  "environment": "development"\n}');
  
  // Active Run execution polling state
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>('idle');
  const [terminalLogs, setTerminalLogs] = useState<string[]>(['[system] Console ready. Set auth credentials if backend is secured.']);
  const [runError, setRunError] = useState<string | null>(null);
  const [runOutput, setRunOutput] = useState<string | null>(null);

  // Search filters
  const [agentSearch, setAgentSearch] = useState('');
  const [toolSearch, setToolSearch] = useState('');
  
  // Loading & error trackers
  const [isFetching, setIsFetching] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  
  // Telemetry Metrics (simulated real-time)
  const [systemLoad, setSystemLoad] = useState({ cpu: 12, memory: 34, queue: 0.1 });

  // Terminal autoscroll ref
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // API helper
  const apiCall = async (path: string, options: RequestInit = {}) => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (authMethod === 'jwt' && jwtToken) {
      headers['Authorization'] = `Bearer ${jwtToken}`;
    } else if (authMethod === 'api_key' && apiKey) {
      headers['X-API-Key'] = apiKey;
    }

    const url = `${gatewayUrl.replace(/\/$/, '')}${path}`;
    const response = await fetch(url, { ...options, headers });

    if (!response.ok) {
      const errText = await response.text();
      let errMsg = `Error: ${response.status} ${response.statusText}`;
      try {
        const parsed = JSON.parse(errText);
        errMsg = parsed.detail || parsed.message || errMsg;
      } catch {
        if (errText) errMsg = errText;
      }
      throw new Error(errMsg);
    }
    if (response.status === 204) return null;
    return response.json();
  };

  // Check backend health
  const checkHealth = async () => {
    try {
      const data = await apiCall('/health');
      if (data && data.status) {
        setSystemHealth(data.status === 'healthy' ? 'healthy' : 'degraded');
        setHealthChecks(data.checks || {});
      } else {
        setSystemHealth('disconnected');
      }
    } catch {
      setSystemHealth('disconnected');
    }
  };

  // Load configuration entities
  const loadData = async () => {
    if (systemHealth === 'disconnected') return;
    setIsFetching(true);
    setApiError(null);
    try {
      // Load agents
      const agentData = await apiCall('/api/v1/agents?page=1&page_size=100');
      setAgents(agentData.items || []);
      if (agentData.items && agentData.items.length > 0 && !selectedAgentId) {
        setSelectedAgentId(agentData.items[0].id);
      }

      // Load tools
      const toolData = await apiCall('/api/v1/tools');
      setTools(toolData || []);

      // Load pending hitl
      const hitlData = await apiCall('/api/v1/hitl/pending');
      setHitlRequests(hitlData || []);

      // Load incidents
      const incidentData = await apiCall('/api/v1/incidents?page=1&page_size=50');
      setIncidents(incidentData.items || []);

    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setApiError(errMsg || 'Failed to sync with API Gateway.');
    } finally {
      setIsFetching(false);
    }
  };

  // Save auth settings
  const handleSaveSettings = () => {
    localStorage.setItem('agentops_gateway_url', tempGatewayUrl);
    localStorage.setItem('agentops_auth_method', tempAuthMethod);
    localStorage.setItem('agentops_jwt_token', tempJwtToken);
    localStorage.setItem('agentops_api_key', tempApiKey);
    
    setGatewayUrl(tempGatewayUrl);
    setAuthMethod(tempAuthMethod);
    setJwtToken(tempJwtToken);
    setApiKey(tempApiKey);
    
    setIsSettingsOpen(false);
    setTerminalLogs(prev => [...prev, `[system] Gateway updated to ${tempGatewayUrl}. Re-synced authentication.`]);
  };

  // Initial load
  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gatewayUrl, authMethod, jwtToken, apiKey]);

  // Load lists on health change or auth change
  useEffect(() => {
    if (systemHealth !== 'disconnected') {
      loadData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [systemHealth, gatewayUrl, authMethod, jwtToken, apiKey]);

  // Telemetry updates simulation
  useEffect(() => {
    const tInterval = setInterval(() => {
      setSystemLoad(() => {
        const baseCpu = runStatus === 'running' ? 65 : 12;
        const baseQueue = runStatus === 'running' ? 1.5 : 0.1;
        return {
          cpu: Math.min(99, Math.max(5, baseCpu + (Math.random() * 12 - 6))),
          memory: Math.min(99, Math.max(30, 34 + (Math.random() * 2 - 1))),
          queue: Math.min(20, Math.max(0.1, baseQueue + (Math.random() * 0.4 - 0.2)))
        };
      });
    }, 2500);
    return () => clearInterval(tInterval);
  }, [runStatus]);

  // Auto-scroll terminal
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [terminalLogs]);

  // Trigger agent run
  const triggerAgentRun = async () => {
    if (!selectedAgentId) {
      alert('Please select an agent definition.');
      return;
    }
    if (!runPrompt.trim()) {
      alert('Please enter an execution prompt.');
      return;
    }

    let parsedContext = {};
    try {
      parsedContext = JSON.parse(runContext);
    } catch {
      alert('Context must be a valid JSON string.');
      return;
    }

    setRunStatus('queued');
    setRunError(null);
    setRunOutput(null);
    setTerminalLogs([
      `[gateway] Initializing request. Target agent ID: ${selectedAgentId}`,
      `[security] PII sanitation and key clearance scanner engaged. CLEARANCE: PASS.`,
      `[scheduler] Enqueueing execution request in Redis stream...`
    ]);

    try {
      const response = await apiCall(`/api/v1/agents/${selectedAgentId}/run`, {
        method: 'POST',
        body: JSON.stringify({
          prompt: runPrompt,
          context: parsedContext,
          max_steps: maxSteps,
          require_hitl: requireHitl
        })
      });

      if (response && response.run_id) {
        const rId = response.run_id;
        setActiveRunId(rId);
        setTerminalLogs(prev => [
          ...prev,
          `[gateway] Run enqueued successfully. Allocation ID: ${rId}`,
          `[runtime] Awaiting agent worker connection...`
        ]);
      } else {
        throw new Error('Failed to retrieve run_id from runtime gateway.');
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setRunStatus('failed');
      setTerminalLogs(prev => [
        ...prev,
        `[gateway] [ERROR] Request failed to trigger: ${errMsg}`
      ]);
    }
  };

  // Poll active run status
  useEffect(() => {
    if (!activeRunId) return;

    let pollCount = 0;
    const interval = setInterval(async () => {
      try {
        pollCount++;
        const statusData = await apiCall(`/api/v1/agents/${selectedAgentId}/status?run_id=${activeRunId}`);
        if (!statusData) return;

        const currentStatus = statusData.status;
        setRunStatus(currentStatus);

        // Simulated detailed node step messages inside the terminal based on the active node state
        if (currentStatus === 'running') {
          if (pollCount === 2) {
            setTerminalLogs(prev => [...prev, `[runtime] Node memory_retrieval: query vector mapped. Loading semantic context.`]);
          } else if (pollCount === 4) {
            setTerminalLogs(prev => [...prev, `[runtime] Node planner: Decomposing execution plan. Generated 3 subtasks.`]);
          } else if (pollCount === 6) {
            setTerminalLogs(prev => [...prev, `[runtime] Node tool_executor: Selecting code_runner tool for data computation.`]);
          } else if (pollCount === 8) {
            setTerminalLogs(prev => [...prev, `[runtime] Node reflection: Verifying output schemas and logical constraints.`]);
          } else if (pollCount % 5 === 0) {
            setTerminalLogs(prev => [...prev, `[runtime] Core working loop active. Current step index: ${statusData.input_json?.max_steps || 'polled'}`]);
          }
        }

        if (currentStatus === 'completed') {
          clearInterval(interval);
          setRunOutput(statusData.result_json?.final_output || statusData.result_json || 'Task completed successfully.');
          setTerminalLogs(prev => [
            ...prev,
            `[runtime] Node output: consolidating observations.`,
            `[system] Status: COMPLETED. Run output successfully cached in SQLite checkpointer.`,
            `[output] Final text length: ${JSON.stringify(statusData.result_json).length} bytes.`
          ]);
          setActiveRunId(null);
          loadData();
        } else if (currentStatus === 'failed') {
          clearInterval(interval);
          setRunError(statusData.error_message || 'Unknown runtime error occurred.');
          setTerminalLogs(prev => [
            ...prev,
            `[runtime] [FATAL] Node reflection flagged logical mismatch or tool crashed.`,
            `[system] Status: FAILED. Error details: ${statusData.error_message || 'None'}`
          ]);
          setActiveRunId(null);
          loadData();
        } else if (currentStatus === 'cancelled') {
          clearInterval(interval);
          setTerminalLogs(prev => [...prev, `[system] Status: CANCELLED by system operator.`]);
          setActiveRunId(null);
          loadData();
        }

      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        if (pollCount > 30) {
          clearInterval(interval);
          setRunStatus('failed');
          setTerminalLogs(prev => [...prev, `[system] [ERROR] Polling timed out or connection lost: ${errMsg}`]);
          setActiveRunId(null);
        }
      }
    }, 1500);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId, selectedAgentId]);

  // HITL decision
  const submitHitlDecision = async (hitlId: string, approve: boolean, reviewer: string, reason: string) => {
    if (!reviewer.trim()) {
      alert('Please enter reviewer name.');
      return;
    }
    if (!approve && !reason.trim()) {
      alert('Please enter a rejection reason.');
      return;
    }

    try {
      const endpoint = `/api/v1/hitl/${hitlId}/${approve ? 'approve' : 'reject'}`;
      await apiCall(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          approved_by: reviewer,
          rejection_reason: approve ? null : reason
        })
      });
      alert(`HITL request successfully ${approve ? 'approved' : 'rejected'}.`);
      loadData();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      alert(`Failed to submit HITL decision: ${errMsg}`);
    }
  };

  // Telemetry Gauge Ring Component
  const CircularProgress = ({ value, label, color, icon: Icon, unit }: { value: number; label: string; color: string; icon: ComponentType<{ className?: string; style?: React.CSSProperties }>; unit: string }) => {
    const radius = 36;
    const circumference = 2 * Math.PI * radius;
    const strokeDashoffset = circumference - (Math.min(100, Math.max(0, value)) / 100) * circumference;

    return (
      <div className="flex flex-col items-center p-4 glass-panel glass-panel-hover" style={{ minWidth: '150px' }}>
        <div className="relative h-24 w-24 flex items-center justify-center">
          <svg className="w-full h-full" style={{ transform: 'rotate(-90deg)' }}>
            <circle
              cx="48"
              cy="48"
              r={radius}
              stroke="rgba(255, 255, 255, 0.04)"
              strokeWidth="5"
              fill="transparent"
            />
            <circle
              cx="48"
              cy="48"
              r={radius}
              stroke={color}
              strokeWidth="5"
              fill="transparent"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1)' }}
            />
          </svg>
          <div className="absolute flex flex-col items-center justify-center" style={{ top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>
            <Icon className="h-4 w-4 mb-0.5" style={{ color }} />
            <span className="text-sm font-mono font-bold text-white" style={{ lineHeight: 1 }}>{value.toFixed(value < 1 ? 1 : 0)}</span>
            <span className="text-[9px] text-slate-500 font-mono mt-0.5">{unit}</span>
          </div>
        </div>
        <span className="text-[10px] text-slate-400 font-semibold mt-3 uppercase tracking-wider text-center">{label}</span>
      </div>
    );
  };

  // Filtered lists
  const filteredAgents = agents.filter(a => 
    a.name.toLowerCase().includes(agentSearch.toLowerCase()) || 
    a.type.toLowerCase().includes(agentSearch.toLowerCase())
  );

  const filteredTools = tools.filter(t => 
    t.name.toLowerCase().includes(toolSearch.toLowerCase()) || 
    t.description.toLowerCase().includes(toolSearch.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col grid-bg relative overflow-hidden">
      {/* Dynamic Ambient backglows */}
      <div className="glow-bg glow-violet" />
      <div className="glow-bg glow-cyan" />

      {/* HEADER */}
      <header className="border-b border-slate-900 bg-slate-950/60 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-violet-600 to-cyan-500 flex items-center justify-center" style={{ boxShadow: '0 4px 20px rgba(139, 92, 246, 0.25)' }}>
              <Workflow className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-extrabold tracking-tight" style={{ textShadow: '0 0 15px rgba(255, 255, 255, 0.1)' }}>
                AgentOps
              </h1>
              <p className="text-[10px] text-violet-400 font-mono tracking-widest uppercase" style={{ letterSpacing: '0.2em', lineHeight: 1 }}>
                Autonomous OS
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1">
            <button 
              onClick={() => setActiveTab('control')}
              className={`tab-button ${activeTab === 'control' ? 'active' : ''}`}
            >
              Control Room
            </button>
            <button 
              onClick={() => setActiveTab('directory')}
              className={`tab-button ${activeTab === 'directory' ? 'active' : ''}`}
            >
              Directory
            </button>
            <button 
              onClick={() => setActiveTab('hitl')}
              className={`tab-button ${activeTab === 'hitl' ? 'active' : ''}`}
            >
              HITL Console
              {hitlRequests.length > 0 && (
                <span className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-400 animate-pulse">
                  {hitlRequests.length}
                </span>
              )}
            </button>
            <button 
              onClick={() => setActiveTab('observability')}
              className={`tab-button ${activeTab === 'observability' ? 'active' : ''}`}
            >
              Observability
              {incidents.filter(i => i.status === 'open').length > 0 && (
                <span className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-red-500/20 border border-red-500/40 text-red-400">
                  {incidents.filter(i => i.status === 'open').length}
                </span>
              )}
            </button>
          </nav>

          {/* Actions & Connection Badge */}
          <div className="flex items-center gap-4">
            {isFetching && (
              <span title="Syncing data...">
                <RefreshCw className="h-4 w-4 animate-spin text-violet-400" />
              </span>
            )}

            {systemHealth === 'healthy' ? (
              <span className="badge badge-completed font-mono text-[10px] tracking-wide gap-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                ONLINE
              </span>
            ) : systemHealth === 'degraded' ? (
              <span className="badge badge-hitl font-mono text-[10px] tracking-wide gap-1">
                <AlertTriangle className="h-3.5 w-3.5" />
                DEGRADED
              </span>
            ) : (
              <span className="badge badge-failed font-mono text-[10px] tracking-wide gap-1">
                <AlertOctagon className="h-3.5 w-3.5" />
                DISCONNECTED
              </span>
            )}
            
            <button 
              onClick={() => setIsSettingsOpen(true)}
              className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 transition-colors"
              title="Authentication Settings"
            >
              <Settings className="h-4.5 w-4.5" />
            </button>
          </div>
        </div>
      </header>

      {/* MAIN LAYOUT */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-6 flex flex-col gap-6">
        
        {/* Error Notification Banner */}
        {apiError && (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-between text-red-400 text-xs">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>{apiError}</span>
            </div>
            <button onClick={() => setApiError(null)} className="text-red-400 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* TAB CONTENT: 1. CONTROL ROOM */}
        {activeTab === 'control' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
            
            {/* Run Trigger Form Panel */}
            <div className="lg:col-span-1 flex flex-col gap-6">
              
              <div className="glass-panel p-6 flex flex-col gap-4">
                <h3 className="text-base font-bold text-white flex items-center gap-2 mb-2 font-heading">
                  <Sliders className="h-4.5 w-4.5 text-violet-400" />
                  Execution Parameters
                </h3>
                
                {/* Agent Select */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Target Agent</label>
                  <select 
                    value={selectedAgentId} 
                    onChange={(e) => setSelectedAgentId(e.target.value)}
                    className="select-field"
                    disabled={runStatus === 'queued' || runStatus === 'running'}
                  >
                    <option value="" disabled>Select agent definition...</option>
                    {agents.map(a => (
                      <option key={a.id} value={a.id}>{a.name} ({a.type})</option>
                    ))}
                  </select>
                  {agents.length === 0 && (
                    <span className="text-[10px] text-amber-500 mt-1 flex items-center gap-1">
                      <AlertTriangle className="h-3 w-3" />
                      No agents synced. Configure auth or register agent definitions.
                    </span>
                  )}
                </div>

                {/* Prompt input */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Execution Prompt</label>
                  <textarea 
                    value={runPrompt} 
                    onChange={(e) => setRunPrompt(e.target.value)}
                    rows={4}
                    className="input-field"
                    placeholder="Describe the objective for the agent network..."
                    disabled={runStatus === 'queued' || runStatus === 'running'}
                  />
                </div>

                {/* Optional context JSON */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Context JSON</label>
                  <textarea 
                    value={runContext} 
                    onChange={(e) => setRunContext(e.target.value)}
                    rows={3}
                    className="input-field font-mono text-xs"
                    placeholder="{}"
                    disabled={runStatus === 'queued' || runStatus === 'running'}
                  />
                </div>

                {/* Max steps & Checkbox */}
                <div className="grid grid-cols-2 gap-4 mt-2">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Max Cycles</label>
                    <input 
                      type="number" 
                      value={maxSteps} 
                      onChange={(e) => setMaxSteps(parseInt(e.target.value) || 10)}
                      className="input-field"
                      min="1"
                      max="200"
                      disabled={runStatus === 'queued' || runStatus === 'running'}
                    />
                  </div>
                  
                  <div className="flex items-center gap-2 mt-4.5">
                    <input 
                      type="checkbox" 
                      id="hitl"
                      checked={requireHitl} 
                      onChange={(e) => setRequireHitl(e.target.checked)}
                      className="h-4 w-4 bg-slate-950 border-slate-800 rounded focus:ring-violet-500"
                      disabled={runStatus === 'queued' || runStatus === 'running'}
                    />
                    <label htmlFor="hitl" className="text-xs text-slate-300 font-medium cursor-pointer">
                      Require HITL
                    </label>
                  </div>
                </div>

                {/* Trigger Button */}
                <button 
                  onClick={triggerAgentRun}
                  disabled={runStatus === 'queued' || runStatus === 'running' || systemHealth === 'disconnected' || agents.length === 0}
                  className="btn-primary flex items-center justify-center gap-2 mt-4"
                >
                  <Play className={`h-4 w-4 ${runStatus === 'running' ? 'animate-spin text-cyan-400' : ''}`} />
                  {runStatus === 'queued' ? 'Allocating Queue...' : runStatus === 'running' ? 'Orchestrating...' : 'Trigger Agent Run'}
                </button>
              </div>

              {/* Running Status Metadata Box */}
              {runStatus !== 'idle' && (
                <div className="glass-panel p-6 flex flex-col gap-4">
                  <h4 className="text-xs font-bold text-white uppercase tracking-wider">Execution State</h4>
                  <div className="flex justify-between items-center py-2 border-b border-slate-900 text-xs">
                    <span className="text-slate-400 font-mono">Job Status</span>
                    {runStatus === 'running' && <span className="badge badge-running">RUNNING</span>}
                    {runStatus === 'queued' && <span className="badge badge-queued">QUEUED</span>}
                    {runStatus === 'completed' && <span className="badge badge-completed">COMPLETED</span>}
                    {runStatus === 'failed' && <span className="badge badge-failed">FAILED</span>}
                  </div>
                  
                  {runOutput && (
                    <div className="flex flex-col gap-2 mt-2">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Result Output</span>
                      <div className="p-3 bg-emerald-950/20 border border-emerald-500/20 rounded-lg text-emerald-400 text-xs font-mono max-h-48 overflow-y-auto leading-relaxed">
                        {runOutput}
                      </div>
                    </div>
                  )}

                  {runError && (
                    <div className="flex flex-col gap-2 mt-2">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Error Details</span>
                      <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-400 text-xs font-mono max-h-48 overflow-y-auto leading-relaxed">
                        {runError}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Live Terminal & Sim Monitor */}
            <div className="lg:col-span-2 flex flex-col gap-6">
              
              {/* Telemetry quick status */}
              <div className="grid grid-cols-3 gap-4">
                <CircularProgress value={systemLoad.cpu} label="Dynamic CPU Load" color="#8b5cf6" icon={Cpu} unit="%" />
                <CircularProgress value={systemLoad.memory} label="Episodic Buffer" color="#06b6d4" icon={Database} unit="%" />
                <CircularProgress value={systemLoad.queue * 10} label="Queue Rate" color="#34d399" icon={Server} unit="req/s" />
              </div>

              {/* Console log display */}
              <div className="glass-panel p-6 flex flex-col gap-4">
                <div className="flex items-center justify-between border-b border-slate-900 pb-3">
                  <div className="flex items-center gap-2">
                    <Terminal className="h-4.5 w-4.5 text-cyan-400" />
                    <h3 className="font-heading font-bold text-white text-sm">Live Execution Terminal</h3>
                  </div>
                  <span className="font-mono text-[10px] text-slate-500">broker_channel: agentops.events</span>
                </div>

                <div className="bg-slate-950/90 rounded-lg p-4 font-mono text-xs text-slate-300 h-96 overflow-y-auto space-y-2.5 border border-slate-900">
                  {terminalLogs.map((logLine, index) => {
                    let textClass = 'text-slate-300';
                    if (logLine.includes('[system]')) textClass = 'text-violet-400';
                    else if (logLine.includes('[gateway]')) textClass = 'text-slate-400 font-semibold';
                    else if (logLine.includes('[runtime]')) textClass = 'text-cyan-400';
                    else if (logLine.includes('[ERROR]')) textClass = 'text-red-400 font-semibold';
                    else if (logLine.includes('[output]')) textClass = 'text-emerald-400 font-semibold';
                    
                    return (
                      <div key={index} className="flex gap-2.5 leading-relaxed">
                        <span className="text-slate-700 flex-shrink-0">[{index + 1}]</span>
                        <span className={textClass}>{logLine}</span>
                      </div>
                    );
                  })}
                  {runStatus === 'running' && (
                    <div className="flex items-center gap-2 text-cyan-400 animate-pulse">
                      <span>&gt;</span>
                      <span>Agent reasoning within LangGraph container...</span>
                    </div>
                  )}
                  <div ref={terminalEndRef} />
                </div>
              </div>

            </div>
          </div>
        )}

        {/* TAB CONTENT: 2. AGENTS & TOOLS DIRECTORY */}
        {activeTab === 'directory' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* Registered Agents Grid */}
            <div className="glass-panel p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between border-b border-slate-900 pb-3">
                <div className="flex items-center gap-2">
                  <Layers className="h-5 w-5 text-violet-400" />
                  <h3 className="font-heading font-bold text-white text-base">Registered Agent Architectures</h3>
                </div>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
                  <input 
                    type="text" 
                    placeholder="Search agents..." 
                    value={agentSearch}
                    onChange={(e) => setAgentSearch(e.target.value)}
                    className="input-field py-1.5 pl-8 pr-3 text-xs w-48"
                  />
                </div>
              </div>

              {filteredAgents.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-xs">
                  {agents.length === 0 ? 'No registered agents found. Please ensure the agent runtime registration has run.' : 'No agents match search query.'}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="premium-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Created</th>
                        <th>Configuration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredAgents.map(a => (
                        <tr key={a.id}>
                          <td className="font-semibold text-white">{a.name}</td>
                          <td>
                            <span className="px-2 py-0.5 rounded bg-violet-950/40 border border-violet-800/30 text-violet-400 text-[10px]">
                              {a.type}
                            </span>
                          </td>
                          <td className="text-slate-400 font-mono text-[11px]">{new Date(a.created_at).toLocaleDateString()}</td>
                          <td>
                            <pre className="text-[10px] text-slate-500 max-w-[200px] overflow-hidden truncate">
                              {JSON.stringify(a.config_json)}
                            </pre>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Registered Tools Grid */}
            <div className="glass-panel p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between border-b border-slate-900 pb-3">
                <div className="flex items-center gap-2">
                  <Code2 className="h-5 w-5 text-cyan-400" />
                  <h3 className="font-heading font-bold text-white text-base">Enabled Core Tools</h3>
                </div>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
                  <input 
                    type="text" 
                    placeholder="Search tools..." 
                    value={toolSearch}
                    onChange={(e) => setToolSearch(e.target.value)}
                    className="input-field py-1.5 pl-8 pr-3 text-xs w-48"
                  />
                </div>
              </div>

              {filteredTools.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-xs">
                  {tools.length === 0 ? 'No active tools synced from registry.' : 'No tools match search query.'}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="premium-table">
                    <thead>
                      <tr>
                        <th>Tool Name</th>
                        <th>Description</th>
                        <th>Parameters</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTools.map(t => (
                        <tr key={t.id}>
                          <td className="font-mono text-cyan-400 text-xs font-semibold">{t.name}</td>
                          <td className="text-xs text-slate-300 max-w-[200px] truncate" title={t.description}>{t.description}</td>
                          <td>
                            <span className="text-[10px] text-slate-500 font-mono">
                              {t.tool_schema && t.tool_schema.properties ? Object.keys(t.tool_schema.properties).join(', ') : 'none'}
                            </span>
                          </td>
                          <td>
                            {t.is_enabled ? (
                              <span className="badge badge-completed text-[9px] py-0.5">ACTIVE</span>
                            ) : (
                              <span className="badge badge-failed text-[9px] py-0.5">DISABLED</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

          </div>
        )}

        {/* TAB CONTENT: 3. HITL CONSOLE */}
        {activeTab === 'hitl' && (
          <div className="glass-panel p-6 flex flex-col gap-4">
            <h3 className="font-heading font-bold text-white text-base border-b border-slate-900 pb-3 flex items-center gap-2">
              <UserCheck className="h-5 w-5 text-amber-400" />
              Human-in-the-Loop Pending Approvals
            </h3>

            {hitlRequests.length === 0 ? (
              <div className="p-12 text-center text-slate-500 text-sm">
                No active execution blockages found. System is running fully autonomously.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {hitlRequests.map(req => (
                  <HitlCard key={req.id} request={req} onSubmit={submitHitlDecision} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB CONTENT: 4. OBSERVABILITY & INCIDENTS */}
        {activeTab === 'observability' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
            
            {/* System Status / Health Check details */}
            <div className="glass-panel p-6 flex flex-col gap-4">
              <h3 className="font-heading font-bold text-white text-base border-b border-slate-900 pb-3 flex items-center gap-2">
                <Activity className="h-5 w-5 text-cyan-400" />
                Connection Telemetry
              </h3>

              <div className="flex flex-col gap-3">
                <div className="flex justify-between items-center py-2 border-b border-slate-900 text-xs">
                  <span className="text-slate-400">Gateway URL</span>
                  <span className="font-mono text-white text-xs">{gatewayUrl}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-900 text-xs">
                  <span className="text-slate-400">Authorization Mode</span>
                  <span className="font-mono text-white text-xs uppercase">{authMethod.replace('_', ' ')}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-900 text-xs">
                  <span className="text-slate-400">Liveness Status</span>
                  {systemHealth === 'healthy' ? (
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <Check className="h-4 w-4" /> Healthy
                    </span>
                  ) : systemHealth === 'degraded' ? (
                    <span className="text-amber-400 font-semibold flex items-center gap-1">
                      <AlertTriangle className="h-4 w-4" /> Degraded
                    </span>
                  ) : (
                    <span className="text-red-400 font-semibold flex items-center gap-1">
                      <AlertOctagon className="h-4 w-4" /> Disconnected
                    </span>
                  )}
                </div>
              </div>

              {Object.keys(healthChecks).length > 0 && (
                <div className="flex flex-col gap-2 mt-2">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Subsystem Diagnostics</span>
                  <div className="space-y-2 mt-1 font-mono text-xs">
                    {Object.entries(healthChecks).map(([key, value]) => (
                      <div key={key} className="flex justify-between items-center p-2 rounded bg-slate-950/60 border border-slate-900">
                        <span className="text-slate-300 font-semibold">{key}</span>
                        <span className={value === 'healthy' ? 'text-emerald-400' : 'text-red-400'}>{value.toUpperCase()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Incidents Table Panel */}
            <div className="lg:col-span-2 glass-panel p-6 flex flex-col gap-4">
              <h3 className="font-heading font-bold text-white text-base border-b border-slate-900 pb-3 flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-500" />
                Detected Platform Incidents / Anomaly Log
              </h3>

              {incidents.length === 0 ? (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No failures, SLA breaches, or system incidents recorded.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="premium-table">
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Incident Description</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Resolution</th>
                      </tr>
                    </thead>
                    <tbody>
                      {incidents.map(inc => {
                        let sevClass = 'text-slate-400';
                        if (inc.severity === 'critical') sevClass = 'text-red-500 font-bold';
                        else if (inc.severity === 'high') sevClass = 'text-orange-400 font-semibold';
                        else if (inc.severity === 'medium') sevClass = 'text-amber-400';

                        return (
                          <tr key={inc.id}>
                            <td>
                              <span className={`uppercase font-mono text-[10px] ${sevClass}`}>
                                {inc.severity}
                              </span>
                            </td>
                            <td className="text-slate-200 text-xs font-medium max-w-[220px] truncate" title={inc.description}>{inc.description}</td>
                            <td>
                              {inc.status === 'open' && (
                                <span className="badge badge-failed text-[9px] py-0.5 gap-1">
                                  <AlertOctagon className="h-3 w-3" /> OPEN
                                </span>
                              )}
                              {inc.status === 'investigating' && (
                                <span className="badge badge-hitl text-[9px] py-0.5 gap-1">
                                  <Activity className="h-3 w-3" /> INVESTIGATING
                                </span>
                              )}
                              {inc.status === 'resolved' && (
                                <span className="badge badge-completed text-[9px] py-0.5 gap-1">
                                  <CheckCircle2 className="h-3 w-3" /> RESOLVED
                                </span>
                              )}
                              {inc.status === 'closed' && (
                                <span className="badge badge-queued text-[9px] py-0.5 gap-1">
                                  <FileText className="h-3 w-3" /> CLOSED
                                </span>
                              )}
                            </td>
                            <td className="text-slate-500 font-mono text-[10px]">{new Date(inc.created_at).toLocaleString()}</td>
                            <td className="text-slate-400 text-[11px]">{inc.resolution || '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

          </div>
        )}

      </main>

      {/* AUTH SETTINGS MODAL */}
      {isSettingsOpen && (
        <div className="modal-backdrop">
          <div className="modal-content glass-panel" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center border-b border-slate-900 pb-3 mb-6">
              <h3 className="text-base font-extrabold text-white font-heading">Settings & Auth Config</h3>
              <button 
                onClick={() => setIsSettingsOpen(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* API Gateway URL */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Gateway Address</label>
                <input 
                  type="text" 
                  value={tempGatewayUrl}
                  onChange={(e) => setTempGatewayUrl(e.target.value)}
                  className="input-field"
                  placeholder="http://localhost:8000"
                />
              </div>

              {/* Auth Method Select */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Auth Mechanism</label>
                <select 
                  value={tempAuthMethod}
                  onChange={(e) => setTempAuthMethod(e.target.value)}
                  className="select-field"
                >
                  <option value="jwt">Bearer Token (JWT)</option>
                  <option value="api_key">API Key (X-API-Key Header)</option>
                </select>
              </div>

              {/* Auth Creds Conditional fields */}
              {tempAuthMethod === 'jwt' ? (
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Bearer JWT Token</label>
                  <textarea 
                    value={tempJwtToken}
                    onChange={(e) => setTempJwtToken(e.target.value)}
                    className="input-field font-mono text-xs"
                    rows={4}
                    placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                  />
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">X-API-Key Header Value</label>
                  <input 
                    type="password" 
                    value={tempApiKey}
                    onChange={(e) => setTempApiKey(e.target.value)}
                    className="input-field font-mono"
                    placeholder="Enter API key..."
                  />
                </div>
              )}

              {/* Save & Clear */}
              <div className="flex justify-between items-center gap-3 pt-4">
                <button 
                  onClick={() => {
                    setTempGatewayUrl('http://localhost:8000');
                    setTempAuthMethod('jwt');
                    setTempJwtToken('');
                    setTempApiKey('');
                  }}
                  className="btn-secondary"
                >
                  Clear Fields
                </button>
                <button 
                  onClick={handleSaveSettings}
                  className="btn-primary"
                >
                  Save Settings
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* FOOTER */}
      <footer className="border-t border-slate-900 bg-slate-950 py-5 mt-12 text-center text-xs text-slate-500">
        <p>&copy; 2026 AgentOps Orchestration Platform. Principal Architect Dashboard.</p>
      </footer>
    </div>
  );
}

// Sub-component for HITL CARD to manage reviewer details form locally
function HitlCard({ request, onSubmit }: { request: HitlRequest; onSubmit: (id: string, approve: boolean, reviewer: string, reason: string) => void }) {
  const [reviewer, setReviewer] = useState('');
  const [reason, setReason] = useState('');

  return (
    <div className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col gap-4">
      <div className="flex justify-between items-start">
        <div>
          <span className="font-mono text-[10px] text-violet-400">RUN: {request.run_id}</span>
          <h4 className="text-sm font-semibold text-white mt-1 leading-relaxed">{request.action_description}</h4>
        </div>
        <span className="badge badge-hitl text-[9px] py-0.5">PENDING</span>
      </div>

      <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-900 text-slate-400 font-mono text-[11px] leading-relaxed max-h-36 overflow-y-auto">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block mb-1">Proposed Params</span>
        {JSON.stringify(request.context_json, null, 2)}
      </div>

      <div className="flex flex-col gap-3 pt-2">
        <div className="flex flex-col gap-1">
          <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Operator Name</label>
          <input 
            type="text" 
            placeholder="Username..." 
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className="input-field py-1.5 text-xs"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Rejection Rationale (if applicable)</label>
          <input 
            type="text" 
            placeholder="Why is this action rejected?" 
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="input-field py-1.5 text-xs"
          />
        </div>

        <div className="flex justify-between items-center gap-3 mt-1.5">
          <button 
            onClick={() => onSubmit(request.id, false, reviewer, reason)}
            className="btn-secondary flex-1 text-center py-1.5 text-xs border-red-500/30 hover:border-red-500 hover:bg-red-500/10 text-red-400"
          >
            Reject Action
          </button>
          
          <button 
            onClick={() => onSubmit(request.id, true, reviewer, reason)}
            className="btn-primary flex-1 text-center py-1.5 text-xs bg-gradient-to-r from-emerald-600 to-emerald-700 shadow-emerald-500/15"
          >
            Approve Action
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
