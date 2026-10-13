import React, { useEffect, useState } from 'react';
import { fetchEvents } from '../api';
import { 
  Terminal, 
  Search, 
  Download, 
  RefreshCw, 
  Filter, 
  CheckCircle2, 
  Clock, 
  Database, 
  Radio, 
  Code2,
  FileSpreadsheet
} from 'lucide-react';

export default function Events() {
  const [events, setEvents] = useState([]);
  const [source, setSource] = useState('all');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const loadEvents = async () => {
    try {
      const res = await fetchEvents({ source, limit: 100 });
      if (res.success) {
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
    downloadAnchor.setAttribute('download', `distributed_voting_audit_log_${Date.now()}.json`);
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
    <div className="events-page" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 className="page-title">Cluster Observability & Audit Log</h2>
          <p className="page-description">
            Live chronological stream of distributed election, consensus, and durable state sync operations.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary"
            onClick={handleExportJson}
            disabled={events.length === 0}
            style={{ padding: '0.45rem 0.85rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
          >
            <Download size={14} />
            Export Audit JSON
          </button>
          <button
            className="btn btn-secondary"
            onClick={loadEvents}
            style={{ padding: '0.45rem 0.85rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
          >
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ marginBottom: '1.5rem', padding: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          {/* Source filters */}
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            {[
              { id: 'all', label: 'All Operations' },
              { id: 'election', label: 'Elections' },
              { id: 'sync', label: 'Log Syncing' }
            ].map((f) => (
              <button
                key={f.id}
                className={`btn btn-secondary ${source === f.id ? 'btn-primary' : ''}`}
                style={{ padding: '0.4rem 0.85rem', fontSize: '0.8rem' }}
                onClick={() => setSource(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Search box */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: '280px' }}>
            <div style={{ position: 'relative', width: '100%' }}>
              <input
                type="text"
                className="form-input"
                placeholder="Search by ID, type, client..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: '2.2rem', paddingRight: '0.8rem', paddingTop: '0.45rem', paddingBottom: '0.45rem', fontSize: '0.85rem' }}
              />
              <Search size={15} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            </div>
          </div>
        </div>
      </div>

      {/* Main Audit Feed Card */}
      <div className="card">
        <div className="card-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Terminal size={20} color="var(--accent-emerald)" />
            Audit Stream ({filteredEvents.length} events logged)
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span className="pulse-dot" style={{ background: 'var(--accent-emerald)' }} />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>LIVE FEED</span>
          </div>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event Category</th>
                <th>Event Action</th>
                <th>Node ID</th>
                <th>Lamport TS</th>
                <th>Subject / Entity</th>
                <th>Execution Payload Details</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2.5rem' }}>
                    {searchQuery ? 'No audit records matching your search query.' : 'No audit events recorded yet.'}
                  </td>
                </tr>
              ) : (
                filteredEvents.map((ev) => {
                  const isElection = ev.source === 'election';
                  return (
                    <tr key={ev.id}>
                      <td>
                        <span 
                          className="badge" 
                          style={{
                            background: isElection ? 'rgba(99, 102, 241, 0.15)' : 'rgba(6, 182, 212, 0.15)',
                            color: isElection ? 'var(--accent-indigo-light)' : 'var(--accent-cyan-light)',
                            border: isElection ? '1px solid rgba(99, 102, 241, 0.3)' : '1px solid rgba(6, 182, 212, 0.3)'
                          }}
                        >
                          {isElection ? <Radio size={12} /> : <Database size={12} />}
                          {ev.source?.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <strong style={{ color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                          {ev.event_type}
                        </strong>
                      </td>
                      <td>
                        <span style={{ 
                          fontSize: '0.75rem', 
                          background: 'rgba(255,255,255,0.05)', 
                          padding: '0.15rem 0.5rem', 
                          borderRadius: '4px',
                          fontWeight: 600
                        }}>
                          Node {ev.node_id}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-emerald-light)' }}>
                          #{ev.lamport_ts}
                        </span>
                      </td>
                      <td>
                        {ev.vote_id ? (
                          <code style={{ fontSize: '0.75rem', color: 'var(--accent-cyan-light)' }}>{ev.vote_id}</code>
                        ) : ev.client_id ? (
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Client: <strong>{ev.client_id}</strong></span>
                        ) : ev.election_term ? (
                          <span style={{ fontSize: '0.8rem', color: 'var(--accent-amber-light)' }}>Term #{ev.election_term}</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>-</span>
                        )}
                      </td>
                      <td style={{ maxWidth: '320px' }}>
                        <code style={{ 
                          fontSize: '0.75rem', 
                          color: 'var(--text-muted)', 
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
      </div>
    </div>
  );
}
