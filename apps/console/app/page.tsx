type Dashboard = {
  archive_count: number;
  avg_value_density: number;
  lane_distribution: Record<string, number>;
  audit_verdicts: Record<string, number>;
  top_recommendation_types: Record<string, number>;
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

function formatNumber(value: number | undefined): string {
  if (value === undefined) {
    return "--";
  }
  return value.toFixed(2);
}

export default async function HomePage() {
  const dashboard = (await fetchJson<Dashboard>("/dashboard")) ?? {
    archive_count: 0,
    avg_value_density: 0,
    lane_distribution: {},
    audit_verdicts: {},
    top_recommendation_types: {},
  };
  const archives = (await fetchJson<ArchiveRecord[]>("/archives?limit=6")) ?? [];
  const latestTaskId = archives[0]?.task_id;
  const advice = latestTaskId ? await fetchJson<EvolveAdvice>(`/tasks/${latestTaskId}/evolve/advice`) : null;

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">ShuYuanAI 2.0 Control Console</div>
            <h1>治理内核运行态与复盘面板</h1>
            <p>
              面板直接读取治理内核的归档投影、VD 看板和演化建议。重点不是“任务数量”，而是
              “哪些制度真的划算、哪些风险在重复出现、哪些规则应该被进化”。
            </p>
          </div>
          <div className="hero-aside">
            <div className="panel">
              <strong>API Base</strong>
              <span>{API_BASE}</span>
            </div>
            <div className="panel">
              <strong>Latest Task</strong>
              <span>{latestTaskId ?? "No archived task"}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>VD Dashboard</h2>
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
            <div className="muted">{Object.entries(dashboard.lane_distribution).map(([k, v]) => `${k}:${v}`).join(" / ") || "--"}</div>
          </article>
          <article className="stat">
            <strong>Audit Verdicts</strong>
            <div className="muted">{Object.entries(dashboard.audit_verdicts).map(([k, v]) => `${k}:${v}`).join(" / ") || "--"}</div>
          </article>
        </div>
      </section>

      <section className="section section-grid">
        <div style={{ gridColumn: "span 7" }}>
          <h2>Recent Archives</h2>
          {archives.length === 0 ? (
            <div className="empty">当前还没有归档记录。先在 API 中跑完整治理链，再回到这里查看。</div>
          ) : (
            <div className="card-list">
              {archives.map((archive) => (
                <article className="archive-card" key={archive.task_id}>
                  <div className="archive-head">
                    <strong>{archive.summary.user_intent ?? archive.task_id}</strong>
                    <span className="muted">{archive.task_id}</span>
                  </div>
                  <div className="archive-meta">
                    <span>Lane {archive.summary.lane ?? "--"} / {archive.summary.level ?? "--"}</span>
                    <span>Audit {archive.summary.audit_verdict ?? "--"}</span>
                    <span>Gate {archive.summary.final_commit_gate ?? "--"}</span>
                    <span>VD {formatNumber(archive.summary.value_density)}</span>
                  </div>
                  <div className="pill-row">
                    {(archive.summary.effective_artifacts ?? []).slice(0, 6).map((artifact) => (
                      <span className="pill" key={artifact}>{artifact}</span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <div style={{ gridColumn: "span 5" }}>
          <h2>Evolve Advice</h2>
          {!advice ? (
            <div className="empty">归档后会在这里出现路由、模板、预算和风险规则的进化建议。</div>
          ) : (
            <div className="panel">
              <strong>{advice.task_id}</strong>
              <div className="advice-list">
                {advice.recommendations.map((item) => (
                  <div className="advice-item" key={`${item.action}-${item.reason}`}>
                    <div>
                      <strong>{item.action}</strong>
                      <div className="muted">{item.reason}</div>
                    </div>
                    <span className={item.priority === "high" ? "priority-high" : "priority-med"}>
                      {item.priority}
                    </span>
                  </div>
                ))}
              </div>
              <div className="pill-row">
                {Object.entries(dashboard.top_recommendation_types).map(([key, value]) => (
                  <span className="pill" key={key}>{key} × {value}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
