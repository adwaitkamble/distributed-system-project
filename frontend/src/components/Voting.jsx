import React, { useState, useRef } from 'react';
import { 
  Vote, 
  CheckCircle2, 
  AlertTriangle, 
  Copy, 
  Check, 
  Search, 
  ShieldCheck, 
  ArrowRight,
  ExternalLink,
  Database,
  Code2
} from 'lucide-react';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import { submitVote, fetchVote } from '../api';

export default function Voting({ nodeInfo, onVoteSuccess }) {
  const [clientId, setClientId] = useState('');
  const [choice, setChoice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [copiedReceipt, setCopiedReceipt] = useState(false);
  const [copiedFullJson, setCopiedFullJson] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);

  // Receipt lookup state
  const [lookupId, setLookupId] = useState('');
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupError, setLookupError] = useState('');
  const [lookingUp, setLookingUp] = useState(false);

  // Animation container ref for GSAP receipt morph
  const morphContainerRef = useRef(null);

  const candidates = [
    {
      name: 'Alice',
      platform: 'Decentralized Architecture & Scalability',
      description: 'Distributed consensus optimization and high-availability clustering.',
      avatar: 'A'
    },
    {
      name: 'Bob',
      platform: 'Fault-Tolerant Consensus & Safety',
      description: 'Formal verification of safety invariants and Byzantine fault resilience.',
      avatar: 'B'
    },
    {
      name: 'Charlie',
      platform: 'Zero-Downtime State Recovery',
      description: 'Durable WAL replication, fast replay, and high write throughput.',
      avatar: 'C'
    }
  ];

  // Kinetic GSAP Morphing Transition: Upon receiving HTTP 201, smoothly reveal receipt
  useGSAP(() => {
    if (feedback?.success && morphContainerRef.current) {
      gsap.fromTo(
        morphContainerRef.current,
        {
          opacity: 0,
          scale: 0.92,
          y: 20,
          rotateX: 6,
        },
        {
          opacity: 1,
          scale: 1,
          y: 0,
          rotateX: 0,
          duration: 0.55,
          ease: 'power3.out',
          force3D: true,
        }
      );
    }
  }, { dependencies: [feedback?.success, feedback?.voteId], scope: morphContainerRef });

  const handleSubmit = async (e) => {
    e.preventDefault();
    const cleanClient = clientId.trim();
    if (!cleanClient) {
      setFeedback({ success: false, message: 'Please enter a valid Voter ID.' });
      return;
    }
    if (!choice) {
      setFeedback({ success: false, message: 'Please select a candidate before submitting your ballot.' });
      return;
    }

    setSubmitting(true);
    setFeedback(null);

    try {
      const res = await submitVote(cleanClient, choice);
      if (res.success) {
        setFeedback({
          success: true,
          voteId: res.vote_id,
          message: 'Ballot successfully committed across quorum peers and logged to MySQL WAL.',
          lamportTs: res.lamport_ts,
          choice: res.choice,
          nodeId: res.node_id,
          rawResponse: res,
        });

        setClientId('');
        setChoice('');
        if (onVoteSuccess) onVoteSuccess();
      } else {
        setFeedback({
          success: false,
          error: res.error,
          message: res.message || 'Vote rejected: write permissions are restricted to the active coordinator.',
          coordinatorId: res.coordinator_id,
        });
      }
    } catch (err) {
      setFeedback({
        success: false,
        error: 'network_error',
        message: `Failed to contact Flask REST bridge: ${err.message}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyReceipt = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedReceipt(true);
    setTimeout(() => setCopiedReceipt(false), 2000);
  };

  const handleCopyFullJson = (data) => {
    if (!data) return;
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopiedFullJson(true);
    setTimeout(() => setCopiedFullJson(false), 2000);
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    const cleanId = lookupId.trim();
    if (!cleanId) return;

    setLookingUp(true);
    setLookupResult(null);
    setLookupError('');

    try {
      const res = await fetchVote(cleanId);
      if (res.success && res.vote) {
        setLookupResult(res.vote);
      } else {
        setLookupError(res.message || `No ballot record found with identifier "${cleanId}".`);
      }
    } catch (err) {
      setLookupError(`Lookup query failed: ${err.message}`);
    } finally {
      setLookingUp(false);
    }
  };

  const isCoordinator = Boolean(nodeInfo?.is_coordinator);
  const coordinatorId = nodeInfo?.coordinator_id ?? 1;

  return (
    <div className="voting-page route-fade-in">
      <div className="page-header">
        <div>
          <h2 className="page-title">Ballot Casting & Verification</h2>
          <p className="page-description">
            Cast cryptographically ordered ballots with monotonic Lamport timestamp guarantees. Each ballot is verified across synchronous 2-Phase Commit replicas before acknowledgment.
          </p>
        </div>
      </div>

      <div className="grid-2">
        {/* Vote Submission Card */}
        <section className="card" aria-labelledby="ballot-submission-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Vote size={18} color="var(--color-indigo)" aria-hidden="true" />
              <h3 id="ballot-submission-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Cast Your Ballot
              </h3>
            </span>
            {isCoordinator ? (
              <span className="badge badge-coordinator">
                <CheckCircle2 size={12} aria-hidden="true" />
                Coordinator Node {nodeInfo?.node_id} (Accepting Writes)
              </span>
            ) : (
              <span className="badge badge-follower">
                <AlertTriangle size={12} aria-hidden="true" />
                Follower Node {nodeInfo?.node_id ?? '?'} (Read-Only)
              </span>
            )}
          </div>

          {/* Follower Write Guard Notice */}
          {!isCoordinator && (
            <div className="alert alert-warning" role="region" aria-label="Follower Node Notice">
              <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
              <div style={{ flex: 1 }}>
                <strong style={{ color: 'var(--color-amber)' }}>Connected to Follower Node {nodeInfo?.node_id ?? '?'}</strong>
                <p style={{ marginTop: '0.25rem', fontSize: '0.84rem' }}>
                  In this distributed architecture, write operations are handled exclusively by the active Coordinator (<strong>Node {coordinatorId}</strong>) to guarantee linearizable consistency and avoid split-brain writes.
                </p>
                <div style={{ marginTop: '0.75rem' }}>
                  <a
                    href={`http://localhost:${5000 + coordinatorId}`}
                    className="btn btn-primary"
                    style={{ fontSize: '0.8125rem', padding: '0.4rem 0.85rem' }}
                  >
                    <span>Switch to Coordinator (Node {coordinatorId})</span>
                    <ExternalLink size={14} aria-hidden="true" />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Locked 60fps Hardware-Accelerated 2PC Loading Mask */}
          {submitting && (
            <div className="vote-loading-ring-container" role="status" aria-live="assertive">
              <div className="vote-loading-ring" aria-hidden="true" />
              <div className="vote-loading-label">Executing Synchronous 2-Phase Commit (2PC)...</div>
              <div className="vote-loading-subtext">
                Replicating Ballot to Quorum • Acquiring Locks • Committing WAL Entry
              </div>
            </div>
          )}

          {/* Submission Feedback & Morphing Receipt Container */}
          <div aria-live="polite">
            {feedback && !submitting && (
              <div 
                ref={morphContainerRef}
                className={`alert ${feedback.success ? 'alert-success' : 'alert-error'} receipt-morph-container`}
                role="alert"
                style={{ marginBottom: '1.5rem' }}
              >
                {feedback.success ? (
                  <CheckCircle2 size={20} style={{ flexShrink: 0, marginTop: '2px', color: 'var(--color-cyan)' }} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={20} style={{ flexShrink: 0, marginTop: '2px', color: 'var(--color-crimson)' }} aria-hidden="true" />
                )}
                <div style={{ flex: 1 }}>
                  <strong style={{ fontSize: '0.95rem' }}>
                    {feedback.success ? 'Consensus Committed: Ballot Verified!' : 'Submission Rejected'}
                  </strong>
                  <p style={{ marginTop: '0.25rem', fontSize: '0.84rem', color: 'var(--color-text-secondary)' }}>
                    {feedback.message}
                  </p>
                  
                  {feedback.voteId && (
                    <div className="receipt-card" style={{ marginTop: '0.85rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 700, color: 'var(--color-cyan)' }}>
                        <span>CRYPTOGRAPHIC DURABLE RECEIPT</span>
                        <span style={{ fontFamily: 'var(--font-mono)' }}>Lamport TS: #{feedback.lamportTs}</span>
                      </div>

                      <div className="receipt-code-box" style={{ marginTop: '0.5rem' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', wordBreak: 'break-all' }}>
                          {feedback.voteId}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleCopyReceipt(feedback.voteId)}
                          className="btn btn-secondary"
                          style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem', height: '28px', flexShrink: 0 }}
                          title="Copy receipt identifier"
                        >
                          {copiedReceipt ? <Check size={13} color="var(--color-cyan)" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                          <span>{copiedReceipt ? 'Copied' : 'Copy'}</span>
                        </button>
                      </div>

                      <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <button
                          type="button"
                          onClick={() => setShowRawJson(!showRawJson)}
                          className="btn btn-secondary"
                          style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
                        >
                          <Code2 size={13} aria-hidden="true" />
                          <span>{showRawJson ? 'Hide JSON Receipt' : 'View Full JSON Receipt'}</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => handleCopyFullJson(feedback.rawResponse)}
                          className="btn btn-secondary"
                          style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
                        >
                          {copiedFullJson ? <Check size={13} color="var(--color-cyan)" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
                          <span>{copiedFullJson ? 'JSON Copied' : 'Copy JSON'}</span>
                        </button>
                      </div>

                      {showRawJson && (
                        <pre
                          style={{
                            marginTop: '0.75rem',
                            padding: '0.85rem',
                            borderRadius: 'var(--radius-sm)',
                            background: '#070A12',
                            border: '1px solid var(--color-border-glass)',
                            color: 'var(--color-cyan-light)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.75rem',
                            overflowX: 'auto',
                            maxHeight: '160px',
                            lineHeight: 1.4
                          }}
                        >
                          {JSON.stringify(feedback.rawResponse, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}

                  {feedback.coordinatorId && (
                    <div style={{ marginTop: '0.85rem' }}>
                      <a
                        href={`http://localhost:${5000 + feedback.coordinatorId}`}
                        className="btn btn-primary"
                        style={{ fontSize: '0.8125rem', padding: '0.4rem 0.85rem' }}
                      >
                        <span>Redirect to Coordinator (Node {feedback.coordinatorId})</span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </a>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="voter-id-input">
                Voter / Client Identifier <span style={{ color: 'var(--color-crimson)' }}>*</span>
              </label>
              <input
                id="voter-id-input"
                type="text"
                className="form-input"
                placeholder="e.g. voter_001, student_42"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                disabled={submitting}
                required
                aria-describedby="voter-id-help"
              />
              <span id="voter-id-help" className="form-helper">
                Each voter ID may only cast one ballot per election. Duplicate submissions will be rejected with HTTP 409.
              </span>
            </div>

            <fieldset className="form-group" style={{ border: 'none', padding: 0 }}>
              <legend className="form-label">
                Select Candidate <span style={{ color: 'var(--color-crimson)' }}>*</span>
              </legend>
              <div className="candidate-selection-list" role="radiogroup" aria-label="Candidate Options">
                {candidates.map((cand) => {
                  const isSelected = choice === cand.name;
                  const radioId = `candidate-${cand.name.toLowerCase()}`;
                  return (
                    <label
                      key={cand.name}
                      htmlFor={radioId}
                      className={`candidate-card-option ${isSelected ? 'is-selected' : ''}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', flex: 1 }}>
                        <div className="candidate-avatar-badge" aria-hidden="true">
                          {cand.avatar}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <strong style={{ fontSize: '0.95rem', color: '#FFFFFF' }}>
                              {cand.name}
                            </strong>
                            <span className="badge badge-neutral" style={{ fontSize: '0.65rem' }}>
                              {cand.platform}
                            </span>
                          </div>
                          <p style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)', marginTop: '0.15rem' }}>
                            {cand.description}
                          </p>
                        </div>
                      </div>

                      <input
                        type="radio"
                        id={radioId}
                        name="candidate-choice"
                        value={cand.name}
                        checked={isSelected}
                        onChange={() => setChoice(cand.name)}
                        disabled={submitting}
                        style={{ marginLeft: '1rem', accentColor: 'var(--color-indigo)' }}
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', padding: '0.75rem', fontSize: '0.9375rem', marginTop: '0.5rem' }}
              disabled={submitting || !clientId.trim() || !choice}
            >
              {submitting ? (
                <>
                  <div className="vote-loading-ring" style={{ width: '16px', height: '16px', borderWidth: '2px', margin: 0 }} aria-hidden="true" />
                  <span>Replicating Ballot Across 2PC Quorum...</span>
                </>
              ) : (
                <>
                  <Vote size={16} aria-hidden="true" />
                  <span>Submit Verified Ballot</span>
                </>
              )}
            </button>
          </form>
        </section>

        {/* Digital Ballot Receipt Verification Card */}
        <section className="card" aria-labelledby="receipt-lookup-title">
          <div className="card-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ShieldCheck size={18} color="var(--color-cyan)" aria-hidden="true" />
              <h3 id="receipt-lookup-title" style={{ fontSize: '1.0625rem', fontWeight: 700, margin: 0 }}>
                Verify Ballot Receipt
              </h3>
            </span>
            <span className="badge badge-neutral">
              <Database size={12} aria-hidden="true" />
              Audit Verification
            </span>
          </div>

          <p className="card-subtitle">
            Query the distributed database to verify that your ballot was durably committed to the state machine with linearizable ordering.
          </p>

          <form onSubmit={handleLookup} style={{ marginBottom: '1.5rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="receipt-lookup-input">
                Receipt Identifier or Ballot Hash
              </label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  id="receipt-lookup-input"
                  type="text"
                  className="form-input"
                  placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                  value={lookupId}
                  onChange={(e) => setLookupId(e.target.value)}
                  disabled={lookingUp}
                  required
                />
                <button
                  type="submit"
                  className="btn btn-secondary"
                  disabled={lookingUp || !lookupId.trim()}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  <Search size={14} aria-hidden="true" />
                  <span>Verify</span>
                </button>
              </div>
            </div>
          </form>

          {lookupError && (
            <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
              <AlertTriangle size={16} style={{ flexShrink: 0 }} aria-hidden="true" />
              <span style={{ fontSize: '0.84rem' }}>{lookupError}</span>
            </div>
          )}

          {lookupResult && (
            <div 
              className="receipt-card"
              style={{ background: 'rgba(6, 182, 212, 0.06)', borderColor: 'var(--color-cyan-glow)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                <span className="badge badge-active">
                  <CheckCircle2 size={12} aria-hidden="true" />
                  Consensus Record Confirmed
                </span>
                <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--color-cyan)' }}>
                  Lamport TS: #{lookupResult.lamport_ts}
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem', fontSize: '0.84rem' }}>
                <div>
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>VOTER HASH</span>
                  <div style={{ fontWeight: 600, color: '#FFFFFF', fontFamily: 'var(--font-mono)' }}>{lookupResult.client_id}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>BALLOT CHOICE</span>
                  <div style={{ fontWeight: 700, color: 'var(--color-cyan)' }}>{lookupResult.choice}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>COMMIT STATUS</span>
                  <div style={{ fontWeight: 600, color: '#34D399' }}>2PC COMMITTED</div>
                </div>
              </div>

              <pre
                style={{
                  marginTop: '0.85rem',
                  padding: '0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  background: '#070A12',
                  border: '1px solid var(--color-border-glass)',
                  color: 'var(--color-cyan-light)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  overflowX: 'auto',
                  lineHeight: 1.4
                }}
              >
                {JSON.stringify(lookupResult, null, 2)}
              </pre>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
