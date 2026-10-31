import React, { useRef, useState, useEffect, useMemo } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Float, Html } from '@react-three/drei';
import * as THREE from 'three';
import gsap from 'gsap';

// Single 3D Node Mesh Component
function ClusterNodeMesh({ node, position, isCoordinator, _isSelected, onClick, onPointerOver, onPointerOut }) {
  const meshRef = useRef();
  const ringRef = useRef();
  const glowRef = useRef();
  const isActive = node.is_active;

  // Determine node palette
  // Coordinator: Electric Indigo #6366F1 / Cyan #06B6D4
  // Follower: Cyan #06B6D4
  // Down: Crimson #E11D48
  const baseColor = useMemo(() => {
    if (!isActive) return new THREE.Color('#E11D48');
    if (isCoordinator) return new THREE.Color('#6366F1');
    return new THREE.Color('#06B6D4');
  }, [isActive, isCoordinator]);

  const emissiveColor = useMemo(() => {
    if (!isActive) return new THREE.Color('#9F1239');
    if (isCoordinator) return new THREE.Color('#818CF8');
    return new THREE.Color('#22D3EE');
  }, [isActive, isCoordinator]);

  // Gentle idle rotation & breathing effect
  useFrame((state, delta) => {
    if (meshRef.current) {
      meshRef.current.rotation.y += delta * (isCoordinator ? 0.8 : 0.4);
      meshRef.current.rotation.x += delta * 0.2;
    }
    if (ringRef.current && isCoordinator) {
      ringRef.current.rotation.z += delta * 1.2;
      const scale = 1 + Math.sin(state.clock.elapsedTime * 3) * 0.08;
      ringRef.current.scale.set(scale, scale, scale);
    }
  });

  return (
    <group position={position}>
      <Float speed={isCoordinator ? 2.5 : 1.5} rotationIntensity={0.3} floatIntensity={0.5}>
        {/* Core Node Sphere */}
        <mesh
          ref={meshRef}
          onClick={onClick}
          onPointerOver={onPointerOver}
          onPointerOut={onPointerOut}
          scale={isCoordinator ? 1.35 : 1.0}
        >
          <icosahedronGeometry args={[0.7, 2]} />
          <meshStandardMaterial
            color={baseColor}
            emissive={emissiveColor}
            emissiveIntensity={isCoordinator ? 0.85 : 0.45}
            roughness={0.25}
            metalness={0.8}
            wireframe={!isActive}
          />
        </mesh>

        {/* Coordinator Orbital Pulsing Corona Ring */}
        {isCoordinator && isActive && (
          <mesh ref={ringRef} rotation={[Math.PI / 2.5, 0, 0]}>
            <torusGeometry args={[1.3, 0.04, 16, 64]} />
            <meshBasicMaterial color="#06B6D4" transparent opacity={0.85} />
          </mesh>
        )}

        {/* Ambient Outer Halo */}
        {isActive && (
          <mesh ref={glowRef} scale={isCoordinator ? 1.8 : 1.35}>
            <sphereGeometry args={[0.7, 16, 16]} />
            <meshBasicMaterial
              color={baseColor}
              transparent
              opacity={isCoordinator ? 0.15 : 0.08}
              side={THREE.BackSide}
            />
          </mesh>
        )}

        {/* 3D Floating Label */}
        <Html distanceFactor={14} position={[0, isCoordinator ? 1.4 : 1.1, 0]} center>
          <div
            style={{
              padding: '0.2rem 0.55rem',
              borderRadius: '999px',
              background: isCoordinator
                ? 'rgba(99, 102, 241, 0.85)'
                : (isActive ? 'rgba(6, 182, 212, 0.75)' : 'rgba(225, 29, 72, 0.85)'),
              border: '1px solid rgba(255, 255, 255, 0.3)',
              color: '#FFFFFF',
              fontSize: '11px',
              fontWeight: 700,
              fontFamily: 'Inter, sans-serif',
              whiteSpace: 'nowrap',
              pointerEvents: 'none',
              boxShadow: '0 2px 10px rgba(0,0,0,0.5)',
              transform: 'translate3d(0,0,0)',
            }}
          >
            Node {node.node_id} {isCoordinator ? '★ LEADER' : ''}
          </div>
        </Html>
      </Float>
    </group>
  );
}

// 3D Inter-Node Connection Beams (gRPC Replication Channels)
function ClusterBeams({ nodes, nodePositions, coordinatorId }) {
  const coordPos = nodePositions[coordinatorId];
  if (!coordPos) return null;

  return (
    <group>
      {nodes.map((n) => {
        if (n.node_id === coordinatorId) return null;
        const targetPos = nodePositions[n.node_id];
        if (!targetPos) return null;

        const points = [
          new THREE.Vector3(...coordPos),
          new THREE.Vector3(...targetPos),
        ];
        const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
        const isPeerActive = n.is_active;

        return (
          <line key={`beam-${n.node_id}`} geometry={lineGeo}>
            <lineBasicMaterial
              color={isPeerActive ? '#06B6D4' : '#E11D48'}
              transparent
              opacity={isPeerActive ? 0.45 : 0.2}
              linewidth={1}
            />
          </line>
        );
      })}
    </group>
  );
}

// Camera Director: Smoothly animates camera on Failover or Coordinator changes
function CameraController({ coordinatorId, nodePositions }) {
  const { camera } = useThree();
  const controlsRef = useRef();

  useEffect(() => {
    const targetCoordPos = nodePositions[coordinatorId];
    if (targetCoordPos) {
      // Smoothly tween camera to emphasize newly elected coordinator without cutscenes
      gsap.to(camera.position, {
        x: targetCoordPos[0] * 0.4,
        y: 4.5,
        z: 7.2,
        duration: 1.6,
        ease: 'power2.inOut',
      });
    }
  }, [coordinatorId, nodePositions, camera]);

  return (
    <OrbitControls
      ref={controlsRef}
      enablePan={false}
      enableZoom={true}
      minDistance={4}
      maxDistance={14}
      maxPolarAngle={Math.PI / 2.05}
      autoRotate={true}
      autoRotateSpeed={0.6}
    />
  );
}

export default function Cluster3DTopology({ nodes = [], coordinatorId = 1, onSelectNode }) {
  const [hoveredNode, setHoveredNode] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  // Compute 3D positions in circular ring mesh
  const nodePositions = useMemo(() => {
    const count = Math.max(nodes.length, 3);
    const radius = 3.8;
    const positions = {};

    nodes.forEach((n, idx) => {
      const theta = (idx / count) * Math.PI * 2;
      const x = Math.sin(theta) * radius;
      const z = Math.cos(theta) * radius;
      const y = n.node_id === coordinatorId ? 0.35 : 0;
      positions[n.node_id] = [x, y, z];
    });

    return positions;
  }, [nodes, coordinatorId]);

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '340px',
        borderRadius: '16px',
        overflow: 'hidden',
        background: 'radial-gradient(circle at 50% 50%, rgba(99, 102, 241, 0.08) 0%, rgba(11, 15, 25, 0.95) 75%)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: 'inset 0 0 40px rgba(0, 0, 0, 0.6)',
      }}
    >
      {/* 3D Canvas */}
      <Canvas
        camera={{ position: [0, 4.8, 7.8], fov: 46 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
      >
        <ambientLight intensity={0.4} />
        <pointLight position={[10, 10, 10]} intensity={1.2} color="#6366F1" />
        <pointLight position={[-10, -5, -10]} intensity={0.8} color="#06B6D4" />
        <directionalLight position={[0, 8, 2]} intensity={0.6} color="#FFFFFF" />

        <CameraController coordinatorId={coordinatorId} nodePositions={nodePositions} />

        <ClusterBeams
          nodes={nodes}
          nodePositions={nodePositions}
          coordinatorId={coordinatorId}
        />

        {nodes.map((n) => {
          const pos = nodePositions[n.node_id] || [0, 0, 0];
          const isLeader = n.node_id === coordinatorId;
          const isSelected = selectedNode?.node_id === n.node_id;

          return (
            <ClusterNodeMesh
              key={n.node_id}
              node={n}
              position={pos}
              isCoordinator={isLeader}
              isSelected={isSelected}
              onClick={() => {
                setSelectedNode(n);
                if (onSelectNode) onSelectNode(n);
              }}
              onPointerOver={() => setHoveredNode(n)}
              onPointerOut={() => setHoveredNode(null)}
            />
          );
        })}
      </Canvas>

      {/* Floating HUD Telemetry Overlay */}
      <div
        style={{
          position: 'absolute',
          top: '12px',
          left: '14px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: 'rgba(11, 15, 25, 0.75)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          padding: '0.4rem 0.85rem',
          borderRadius: '999px',
          fontSize: '11px',
          fontFamily: 'JetBrains Mono, monospace',
          color: '#94A3B8',
          pointerEvents: 'none',
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
        }}
      >
        <span
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: '#06B6D4',
            boxShadow: '0 0 8px #06B6D4',
            display: 'inline-block',
          }}
        />
        <span>R3F 3D MESH • DRAG TO ROTATE • LEADER: NODE {coordinatorId}</span>
      </div>

      {/* Hover Node Card */}
      {hoveredNode && (
        <div
          style={{
            position: 'absolute',
            bottom: '12px',
            right: '14px',
            background: 'rgba(11, 15, 25, 0.88)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            border: `1px solid ${hoveredNode.node_id === coordinatorId ? '#6366F1' : (hoveredNode.is_active ? '#06B6D4' : '#E11D48')}`,
            borderRadius: '10px',
            padding: '0.65rem 0.95rem',
            fontSize: '11px',
            color: '#E2E8F0',
            pointerEvents: 'none',
            boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
            transform: 'translate3d(0,0,0)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
            <strong style={{ color: '#FFFFFF', fontSize: '13px' }}>Node {hoveredNode.node_id}</strong>
            <span
              style={{
                fontSize: '9px',
                padding: '1px 5px',
                borderRadius: '4px',
                background: hoveredNode.node_id === coordinatorId ? 'rgba(99, 102, 241, 0.25)' : 'rgba(6, 182, 212, 0.25)',
                color: hoveredNode.node_id === coordinatorId ? '#818CF8' : '#22D3EE',
                fontWeight: 700,
              }}
            >
              {hoveredNode.node_id === coordinatorId ? 'COORDINATOR' : 'FOLLOWER'}
            </span>
          </div>
          <div style={{ color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace' }}>
            Status: <span style={{ color: hoveredNode.is_active ? '#34D399' : '#F87171' }}>{hoveredNode.is_active ? 'HEALTHY' : 'DOWN'}</span>
            <br />
            gRPC Port: 5005{hoveredNode.node_id} • HTTP: 500{hoveredNode.node_id}
          </div>
        </div>
      )}
    </div>
  );
}
