// --- COGNITIVE WORKFLOW DEFINITIONS ---
export interface WorkflowStep {
  id: string;
  name: string;
  agentRole: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  dependencies: string[];
  commandPrompt: string;
  resultPayloadPath?: string;
  completedAt?: string;
}

export interface OrchestrationWorkflow {
  id: string;
  title: string;
  creatorId: string;
  status: 'queued' | 'active' | 'success' | 'failed' | 'paused';
  steps: WorkflowStep[];
  metaData: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

// --- SYSTEM TELEMETRY AND METRICS ---
export interface EngineMetrics {
  cpuLoad: number;
  memoryUsageBytes: number;
  activeWorkers: number;
  tasksCompleted: number;
  queueDepth: number;
  telemetrySpanCount: number;
}

// --- MEMORY AND SECURITY POLICIES ---
export interface SecurityContext {
  userId: string;
  roles: ('admin' | 'operator' | 'auditor')[];
  clearanceLevel: number;
  redactionPolicy: 'strict' | 'standard' | 'none';
}

export interface EpisodicMemoryNode {
  key: string;
  sessionToken: string;
  payloadJson: string;
  expirationSeconds: number;
}

export interface SemanticMemoryRecord {
  id: string;
  vector: number[];
  payloadText: string;
  metadata: {
    originTask: string;
    timestamp: string;
    tokenCount: number;
  };
}
