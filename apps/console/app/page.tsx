type Dashboard = {
  archive_count: number;
  avg_value_density: number;
  lane_distribution: Record<string, number>;
  audit_verdicts: Record<string, number>;
  top_recommendation_types: Record<string, number>;
};

type TaskRecord = {
  task_id: string;
  trace_id: string;
  created_at: string;
  user_intent?: string;
  status: string;
  current_state: string;
  archived_at?: string | null;
};

type ArchiveRecord = {
  task_id: string;
  trace_id: string;
  archived_at: string;
  summary: {
    user_intent?: string;
    lane?: string;
    level?: string;
    audit_verdict?: string;
    final_commit_gate?: string;
    value_density?: number;
    effective_artifacts?: string[];
  };
  retrospective: {
    recommendations?: string[];
  };
};

type OperationStatus = {
  task_id: string;
  operation: string;
  status: string;
  error?: string;
  artifact_type?: string;
  updated_at?: string;
};

type YushiContext = {
  task_id: string;
  trace_id: string;
  lane?: string;
  level?: string;
  scores: Record<string, number | null>;
  policy: {
    verdict: string;
    policy_mode: string;
    data_sensitivity?: string | null;
    compliance_domain?: string[];
    required_actions?: string[];
  };
  budget: {
    token_cap: number;
    token_used: number;
    time_cap_s: number;
    tool_cap: number;
    tool_used: number;
  };
  effective_version: Record<string, string>;
  artifacts: Record<
    string,
    {
      event_id: string;
      artifact_id: string;
      version: number;
      envelope: {
        summary?: string;
        body?: Record<string, unknown>;
      };
    }
  >;
  signals: Record<string, unknown>;
};

type RouteDecision = {
  lane_choice: string;
  complexity_level: string;
  module_set: string[];
  route_reason: string;
  budget_plan: {
    token_cap: number;
    time_cap_s: number;
    tool_cap: number;
  };
  governance_contract: {
    confidence: number;
    exit_conditions: Record<string, string[]>;
    commit_requirements: Record<string, string[]>;
  };
};

type EventEnvelope = {
  header: {
    event_id: string;
    timestamp: string;
    stage: string;
    artifact_type: string;
    producer_agent: string;
  };
  summary: string;
};

type EvolveAdvice = {
  task_id: string;
  recommendations: Array<{
    category: string;
    priority: string;
    action: string;
    reason: string;
  }>;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000/api/v2";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function formatNumber(value: number | undefined | null): string {
  if (value === undefined || value === null) {
    return "--";
  }
  return value.toFixed(2);
}

function formatTime(value?: string | null): string {
  if (!value) {
    return "--";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function compactJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export default async function HomePage() {
  const dashboard = (await fetchJson<Dashboard>("/dashboard")) ?? {
    archive_count: 0,
    avg_value_density: 0,
    lane_distribution: {},
    audit_verdicts: {},
    top_recommendation_types: {},
  };
  const tasks = (await fetchJson<TaskRecord[]>("/tasks?limit=8")) ?? [];
  const archives = (await fetchJson<ArchiveRecord[]>("/archives?limit=6")) ?? [];
  const activeTask = tasks.find((item) => item.current_state !== "archived") ?? tasks[0] ?? null;
  const selectedTaskId = activeTask?.task_id ?? archives[0]?.task_id ?? null;

  const [context, routeDecision, events, roundtableStatus, challengeStatus, auditStatus, advice] = selectedTaskId
    ? await Promise.all([
        fetchJson<YushiContext>(`/tasks/${selectedTaskId}/extractors/yushi-context`),
        fetchJson<RouteDecision>(`/tasks/${selectedTaskId}/route-decision`),
        fetchJson<EventEnvelope[]>(`/tasks/${selectedTaskId}/events`),
        fetchJson<OperationStatus>(`/tasks/${selectedTaskId}/operations/roundtable`),
        fetchJson<OperationStatus>(`/tasks/${selectedTaskId}/operations/challenge`),
        fetchJson<OperationStatus>(`/tasks/${selectedTaskId}/operations/audit`),
        fetchJson<EvolveAdvice>(`/tasks/${selectedTaskId}/evolve/advice`),
      ])
    : [null, null, null, null, null, null, null];

  const artifactEntries = Object.entries(context?.artifacts ?? {}).slice(0, 8);
  const signalEntries = Object.entries(context?.signals ?? {}).slice(0, 6);

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">ShuYuanAI 2.0 Governance Console</div>
            <h1>治理控制台</h1>
            <p>
              这个面板不只看归档结果，还把任务路由、治理契约、动态委员会、挑战与审计运行态拉到同一屏。
              核心用途是审阅当前任务是否仍然遵守 2.0 约束，而不是只看最终产物。
            </p>
          </div>
          <div className="hero-aside">
            <div className="panel">
              <strong>API Base</strong>
              <span>{API_BASE}</span>
            </div>
            <div className="panel">
              <strong>Focused Task</strong>
              <span>{selectedTaskId ?? "No task"}</span>
            </div>
            <div className="panel">
              <strong>Current State</strong>
              <span>{activeTask?.current_state ?? "--"}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Control Plane</h2>
        <div className="stats">
          <article className="stat">
            <strong>Archive Count</strong>
            <div className="stat-value">{dashboard.archive_count}</div>
          </article>
          <article className="stat">
            <strong>Avg VD</strong>
            <div className="stat-value">{formatNumber(dashboard.avg_value_density)}</div>
          </article>
          <article className="stat">
            <strong>Lane Mix</strong>
            <div className="muted">
              {Object.entries(dashboard.lane_distribution)
                .map(([key, value]) => `${key}:${value}`)
                .join(" / ") || "--"}
            </div>
          </article>
          <article className="stat">
            <strong>Audit Verdicts</strong>
            <div className="muted">
              {Object.entries(dashboard.audit_verdicts)
                .map(([key, value]) => `${key}:${value}`)
                .join(" / ") || "--"}
            </div>
          </article>
        </div>
      </section>

      <section className="section section-grid">
        <div className="span-5">
          <h2>Task Board</h2>
          {tasks.length === 0 ? (
            <div className="empty">当前还没有任务记录。</div>
          ) : (
            <div className="panel task-list">
              {tasks.map((task) => (
                <article className={task.task_id === selectedTaskId ? "task-row active" : "task-row"} key={task.task_id}>
                  <div>
                    <strong>{task.user_intent ?? task.task_id}</strong>
                    <div className="muted mono">{task.task_id}</div>
                  </div>
                  <div className="task-meta">
                    <span className="pill neutral">{task.current_state}</span>
                    <span className="muted">{formatTime(task.created_at)}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="span-7">
          <h2>Task Review</h2>
          {!selectedTaskId || !context ? (
            <div className="empty">选择任务后会显示路由、信号、事件与有效产物。</div>
          ) : (
            <div className="stack">
              <div className="review-grid">
                <article className="panel">
                  <div className="section-head">
                    <strong>Route Contract</strong>
                    <span className="pill accent">
                      {routeDecision?.lane_choice ?? context.lane ?? "--"} / {routeDecision?.complexity_level ?? context.level ?? "--"}
                    </span>
                  </div>
                  <div className="muted">理由：{routeDecision?.route_reason ?? "--"}</div>
                  <div className="pill-row">
                    {(routeDecision?.module_set ?? []).map((module) => (
                      <span className="pill" key={module}>
                        {module}
                      </span>
                    ))}
                  </div>
                  <div className="mini-grid">
                    <div>
                      <strong>Budget</strong>
                      <div className="muted">
                        {routeDecision
                          ? `${routeDecision.budget_plan.token_cap} / ${routeDecision.budget_plan.time_cap_s}s / ${routeDecision.budget_plan.tool_cap}`
                          : "--"}
                      </div>
                    </div>
                    <div>
                      <strong>Exit</strong>
                      <div className="muted">
                        {routeDecision
                          ? Object.entries(routeDecision.governance_contract.exit_conditions)
                              .map(([key, value]) => `${key}:${value.length}`)
                              .join(" / ")
                          : "--"}
                      </div>
                    </div>
                  </div>
                </article>

                <article className="panel">
                  <div className="section-head">
                    <strong>Runtime Status</strong>
                    <span className="pill gold">{activeTask?.current_state ?? "--"}</span>
                  </div>
                  <div className="status-list">
                    {[roundtableStatus, challengeStatus, auditStatus].map((item, index) => (
                      <div className="status-item" key={`${item?.operation ?? "idle"}-${index}`}>
                        <div>
                          <strong>{item?.operation ?? ["roundtable", "challenge", "audit"][index]}</strong>
                          <div className="muted">{item?.updated_at ? formatTime(item.updated_at) : "idle"}</div>
                        </div>
                        <span className={`pill ${item?.status === "failed" ? "danger" : item?.status === "completed" ? "success" : "neutral"}`}>
                          {item?.status ?? "idle"}
                        </span>
                      </div>
                    ))}
                  </div>
                </article>
              </div>

              <div className="review-grid">
                <article className="panel">
                  <div className="section-head">
                    <strong>Signal Ledger</strong>
                    <span className="pill neutral">{context.policy.verdict}</span>
                  </div>
                  <div className="kv-grid">
                    <div>
                      <label>Scores</label>
                      <div className="muted mono">
                        {Object.entries(context.scores)
                          .map(([key, value]) => `${key}:${value ?? "--"}`)
                          .join(" / ")}
                      </div>
                    </div>
                    <div>
                      <label>Budget Usage</label>
                      <div className="muted mono">
                        {context.budget.token_used}/{context.budget.token_cap} tokens · {context.budget.tool_used}/{context.budget.tool_cap} tools
                      </div>
                    </div>
                    <div>
                      <label>Data / Compliance</label>
                      <div className="muted">
                        {context.policy.data_sensitivity ?? "--"} · {(context.policy.compliance_domain ?? []).join(", ") || "--"}
                      </div>
                    </div>
                  </div>
                  <div className="signal-list">
                    {signalEntries.map(([key, value]) => (
                      <div className="signal-item" key={key}>
                        <strong>{key}</strong>
                        <pre>{compactJson(value)}</pre>
                      </div>
                    ))}
                  </div>
                </article>

                <article className="panel">
                  <div className="section-head">
                    <strong>Effective Artifacts</strong>
                    <span className="pill neutral">{artifactEntries.length}</span>
                  </div>
                  <div className="artifact-list">
                    {artifactEntries.map(([name, artifact]) => (
                      <div className="artifact-card" key={name}>
                        <div className="artifact-head">
                          <strong>{name}</strong>
                          <span className="pill neutral">{context.effective_version[name] ?? `v${artifact.version}`}</span>
                        </div>
                        <div className="muted mono">{artifact.event_id}</div>
                        <div className="artifact-summary">{artifact.envelope.summary ?? "no summary"}</div>
                        <pre>{compactJson(artifact.envelope.body ?? {})}</pre>
                      </div>
                    ))}
                  </div>
                </article>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="section section-grid">
        <div className="span-7">
          <h2>Event Timeline</h2>
          {!events || events.length === 0 ? (
            <div className="empty">当前任务还没有事件时间线。</div>
          ) : (
            <div className="timeline">
              {events.slice(-10).reverse().map((event) => (
                <article className="timeline-item" key={event.header.event_id}>
                  <div className="timeline-dot" />
                  <div className="timeline-body">
                    <div className="timeline-head">
                      <strong>{event.header.artifact_type}</strong>
                      <span className="pill neutral">{event.header.stage}</span>
                    </div>
                    <div className="muted">
                      {event.header.event_id} · {event.header.producer_agent} · {formatTime(event.header.timestamp)}
                    </div>
                    <p>{event.summary}</p>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="span-5">
          <h2>Archive & Evolve</h2>
          <div className="stack">
            {archives.length === 0 ? (
              <div className="empty">当前还没有归档记录。</div>
            ) : (
              <div className="panel card-list">
                {archives.map((archive) => (
                  <article className="archive-card" key={archive.task_id}>
                    <div className="archive-head">
                      <strong>{archive.summary.user_intent ?? archive.task_id}</strong>
                      <span className="muted mono">{archive.task_id}</span>
                    </div>
                    <div className="archive-meta">
                      <span>Lane {archive.summary.lane ?? "--"} / {archive.summary.level ?? "--"}</span>
                      <span>Gate {archive.summary.final_commit_gate ?? "--"}</span>
                      <span>VD {formatNumber(archive.summary.value_density)}</span>
                    </div>
                    <div className="pill-row">
                      {(archive.summary.effective_artifacts ?? []).slice(0, 5).map((artifact) => (
                        <span className="pill" key={artifact}>
                          {artifact}
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}

            <div className="panel">
              <div className="section-head">
                <strong>Evolve Advice</strong>
                <span className="pill gold">{advice?.recommendations.length ?? 0}</span>
              </div>
              {!advice ? (
                <div className="empty compact">当前任务还没有形成 evolve advice。</div>
              ) : (
                <div className="advice-list">
                  {advice.recommendations.map((item) => (
                    <div className="advice-item" key={`${item.action}-${item.reason}`}>
                      <div>
                        <strong>{item.action}</strong>
                        <div className="muted">{item.reason}</div>
                      </div>
                      <span className={item.priority === "high" ? "priority-high" : "priority-med"}>{item.priority}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
