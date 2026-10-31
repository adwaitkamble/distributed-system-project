import React, { useEffect, useState, useRef } from 'react';
import { fetchEvents } from '../api';
import { 
  Terminal, 
  Table,
  Search, 
  Download, 
  RefreshCw, 
  Database, 
  Radio
} from 'lucide-react';

export default function Events() {
  const [events, setEvents] = useState([]);
  const [source, setSource] = useState('all');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'terminal'
  const [autoScroll, setAutoScroll] = useState(true);

  // Track newly polled event IDs for subtle row entry animation & Lamport pulse
  const prevEventIdsRef = useRef(new Set());
  const [newlyAddedIds, setNewlyAddedIds] = useState(new Set());
  const terminalEndRef = useRef(null);

  const loadEvents = async () => {
    try {
      const res = await fetchEvents({ source, limit: 100 });
      if (res?.success) {
        const incoming = res.events || [];

        // Detect newly arrived events
        if (prevEventIdsRef.current.size > 0) {
          const freshIds = new Set();
          incoming.forEach((ev) => {
            if (!prevEventIdsRef.current.has(ev.id)) {
              freshIds.add(ev.id);
            }
          });
          if (freshIds.size > 0) {
            setNewlyAddedIds(freshIds);
            setTimeout(() => {
              setNewlyAddedIds(new Set());
            }, 2200);
          }
        }

        prevEventIdsRef.current = new Set(incoming.map((ev) => ev.id));
        setEvents(incoming);
      }
    } catch (err) {
      console.error('Failed to load events:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
    const interval = setInterval(loadEvents, 3000);
    return () => clearInterval(interval);
  }, [source]);

  // Handle auto-scroll in live console mode
  useEffect(() => {
    if (viewMode === 'terminal' && autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, viewMode, autoScroll]);

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(events, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `distributed_voting_audit_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const filteredEvents = events.filter((ev) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    const typeMatch = ev.event_type?.toLowerCase().includes(q);
    const idMatch = String(ev.node_id).includes(q) || String(ev.lamport_ts).includes(q);
    const clientMatch = ev.client_id?.toLowerCase().includes(q);
    const voteMatch = ev.vote_id?.toLowerCase().includes(q);
    const detailsMatch = JSON.stringify(ev.details || '').toLowerCase().includes(q);
    return typeMatch || idMatch || clientMatch || voteMatch || detailsMatch;
  });

  return (
    <div className="events-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Cluster Observability & Audit Stream</h2>
          <p className="page-description">
            Chronological audit stream of consensus transitions, coordinator elections, and distributed state synchronizations.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          {/* Dual-View Mode Switcher */}
          <div className="view-mode-toggle" role="group" aria-label="Select audit stream view mode">
            <button
              type="button"
              className={`view-mode-btn ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
              aria-pressed={viewMode === 'table'}
              title="Structured table for invariant verification"
            >
              <Table size={13} aria-hidden="true" />
              <span>Table View</span>
            </button>
            <button
              type="button"
              className={`view-mode-btn ${viewMode === 'terminal' ? 'active' : ''}`}
              onClick={() => setViewMode('terminal')}
              aria-pressed={viewMode === 'terminal'}
              title="Live streaming console log"
            >
              <Terminal size={13} aria-hidden="true" />
              <span>Live Console</span>
            </button>
          </div>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleExportJson}
            disabled={events.length === 0}
            style={{ padding: '0.4rem 0.85rem', fontSize: '0.8125rem' }}
          >
            <Download size={14} aria-hidden="true" />
            <span>Export Audit JSON</span>
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadEvents}
            style={{ padding: '0.4rem 0.85rem', fontSize: '0.8125rem' }}
          >
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} aria-hidden="true" />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ marginBottom: '1.5rem', padding: '1rem 1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          {/* Source filters */}
          <div style={{ display: 'flex', gap: '0.35rem' }} role="group" aria-label="Filter events by source">
            {[
              { id: 'all', label: 'All Operations' },
              { id: 'election', label: 'Elections' },
              { id: 'sync', label: 'SyncLog Replays' }
            ].map((f) => (
              <button
                key={f.id}
                type="button"
                className={`btn ${source === f.id ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '0.35rem 0.75rem', fontSize: '0.8125rem' }}
                onClick={() => setSource(f.id)}
                aria-pressed={source === f.id}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Search box */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: '280px', flex: '1 1 auto', maxWidth: '400px' }}>
            <div style={{ position: 'relative', width: '100%' }}>
              <input
                type="search"
                className="form-input"
                placeholder="Search audit records by ID, node, or type..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: '2.1rem', paddingRight: '0.75rem', paddingTop: '0.45rem', paddingBottom: '0.45rem', fontSize: '0.84rem' }}
                aria-label="Search audit records"
              />
              <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} aria-hidden="true" />
            </div>
          </div>
        </div>
      </div>

      {/* VIEW 1: Structured Audit Table View */}
      {viewMode === 'table' && (
        <section className="card" aria-labelledby="audit-table-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Table size={18} color="var(--color-teal-accent)" aria-hidden="true" />
              <h3 id="audit-table-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Live Audit Log ({filteredEvents.length} events logged)
              </h3>
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span className="status-dot status-dot-active" aria-hidden="true" />
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', fontWeight: 600 }}>MONITORED</span>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table" aria-label="Audit Log Table">
              <thead>
                <tr>
                  <th scope="col">Category</th>
                  <th scope="col">Event Action</th>
                  <th scope="col">Node ID</th>
                  <th scope="col">Lamport TS</th>
                  <th scope="col">Entity / Context</th>
                  <th scope="col">Execution Details</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: '2rem' }}>
                      {searchQuery ? 'No audit records matching your search query.' : 'No audit events recorded yet.'}
                    </td>
                  </tr>
                ) : (
                  filteredEvents.map((ev) => {
                    const isElection = ev.source === 'election';
                    const isNew = newlyAddedIds.has(ev.id);

                    return (
                      <tr 
                        key={ev.id} 
                        className={isNew ? 'ledger-row-new' : ''}
                      >
                        <td>
                          <span className={`badge ${isElection ? 'badge-follower' : 'badge-neutral'}`}>
                            {isElection ? <Radio size={12} aria-hidden="true" /> : <Database size={12} aria-hidden="true" />}
                            <span>{ev.source?.toUpperCase()}</span>
                          </span>
                        </td>
                        <td>
                          <strong style={{ color: 'var(--color-navy-primary)', fontSize: '0.84rem' }}>
                            {ev.event_type}
                          </strong>
                        </td>
                        <td>
                          <span style={{ fontSize: '0.75rem', backgroundColor: 'var(--color-surface-subtle)', padding: '0.15rem 0.45rem', borderRadius: '4px', fontWeight: 600 }}>
                            Node {ev.node_id}
                          </span>
                        </td>
                        <td>
                          <span 
                            style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-navy-primary)', fontWeight: 600 }}
                            className={isNew ? 'lamport-badge-new' : ''}
                          >
                            #{ev.lamport_ts}
                          </span>
                        </td>
                        <td>
                          {ev.vote_id ? (
                            <code style={{ fontSize: '0.75rem' }}>{ev.vote_id}</code>
                          ) : ev.client_id ? (
                            <span style={{ fontSize: '0.8rem' }}>Client: <strong>{ev.client_id}</strong></span>
                          ) : ev.election_term !== undefined && ev.election_term !== null ? (
                            <span style={{ fontSize: '0.8rem' }}>Term #{ev.election_term}</span>
                          ) : (
                            <span style={{ color: 'var(--color-text-muted)' }}>-</span>
                          )}
                        </td>
                        <td style={{ maxWidth: '300px' }}>
                          <code style={{ 
                            fontSize: '0.75rem', 
                            color: 'var(--color-text-secondary)', 
                            display: 'block', 
                            overflow: 'hidden', 
                            textOverflow: 'ellipsis', 
                            whiteSpace: 'nowrap' 
                          }}>
                            {typeof ev.details === 'object' ? JSON.stringify(ev.details) : String(ev.details || '-')}
                          </code>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* VIEW 2: Streaming Console Terminal View */}
      {viewMode === 'terminal' && (
        <section className="terminal-window" aria-label="Live gRPC & Consensus Terminal Stream">
          <div className="terminal-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div className="terminal-dots" aria-hidden="true">
                <span className="terminal-dot terminal-dot-red" />
                <span className="terminal-dot terminal-dot-yellow" />
                <span className="terminal-dot terminal-dot-green" />
              </div>
              <span style={{ fontWeight: 600, color: '#E2E8F0', letterSpacing: '0.04em' }}>
                grpc://consensus-mesh • audit-stream.log
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer', fontSize: '0.75rem' }}>
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)}
                  style={{ accentColor: '#2DD4BF' }}
                />
                <span>Auto-scroll</span>
              </label>
              <span style={{ color: '#64748B' }}>{filteredEvents.length} frames logged</span>
            </div>
          </div>

          <div className="terminal-body" role="log" aria-live="polite">
            {filteredEvents.length === 0 ? (
              <div style={{ color: '#64748B', fontStyle: 'italic', padding: '1.5rem 0' }}>
                -- Waiting for cluster consensus events --
              </div>
            ) : (
              filteredEvents.map((ev) => {
                const isElection = ev.source === 'election';
                const isNew = newlyAddedIds.has(ev.id);
                const timeStr = ev.created_at ? new Date(ev.created_at).toISOString().substring(11, 23) : '--:--:--.---';
                const payloadStr = typeof ev.details === 'object' ? JSON.stringify(ev.details) : String(ev.details || '');

                return (
                  <div 
                    key={ev.id} 
                    className={`terminal-line ${isNew ? 'ledger-row-new' : ''}`}
                  >
                    <span className="terminal-timestamp">[{timeStr}]</span>
                    <span className="terminal-node-tag">[NODE {ev.node_id}]</span>
                    <span className="terminal-lamport">[L:#{ev.lamport_ts}]</span>
                    <span className={isElection ? 'terminal-source-election' : 'terminal-source-sync'}>
                      [{ev.source?.toUpperCase()}]
                    </span>
                    <span className="terminal-event-name">{ev.event_type}</span>
                    {ev.vote_id && <span style={{ color: '#38BDF8' }}>vote:{ev.vote_id}</span>}
                    {ev.client_id && <span style={{ color: '#E2E8F0' }}>voter:{ev.client_id}</span>}
                    {ev.election_term !== undefined && ev.election_term !== null && (
                      <span style={{ color: '#FBBF24' }}>term:#{ev.election_term}</span>
                    )}
                    {payloadStr && payloadStr !== '{}' && (
                      <span className="terminal-payload">→ {payloadStr}</span>
                    )}
                  </div>
                );
              })
            )}
            <div ref={terminalEndRef} />
          </div>
        </section>
      )}
    </div>
  );
}
