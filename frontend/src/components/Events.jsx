import React, { useEffect, useState } from 'react';
import { fetchEvents } from '../api';
import { 
  Terminal, 
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

  const loadEvents = async () => {
    try {
      const res = await fetchEvents({ source, limit: 100 });
      if (res?.success) {
        setEvents(res.events || []);
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

      {/* Main Audit Feed Card */}
      <section className="card" aria-labelledby="audit-table-title">
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Terminal size={18} color="var(--color-teal-accent)" aria-hidden="true" />
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
                  return (
                    <tr key={ev.id}>
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
                        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-navy-primary)', fontWeight: 600 }}>
                          #{ev.lamport_ts}
                        </span>
                      </td>
                      <td>
                        {ev.vote_id ? (
                          <code style={{ fontSize: '0.75rem' }}>{ev.vote_id}</code>
                        ) : ev.client_id ? (
                          <span style={{ fontSize: '0.8rem' }}>Client: <strong>{ev.client_id}</strong></span>
                        ) : ev.election_term ? (
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
    </div>
  );
}
