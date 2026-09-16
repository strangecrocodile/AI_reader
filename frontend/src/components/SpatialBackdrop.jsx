import { useEffect, useRef } from 'react';

export default function SpatialBackdrop() {
  const mountRef = useRef(null);

  useEffect(() => {
    let cleanupScene = () => {};
    let disposed = false;

    async function setupScene() {
      const mount = mountRef.current;
      if (!mount || typeof window === 'undefined' || !window.WebGLRenderingContext) {
        return;
      }

      const THREE = await import('three');
      if (disposed) {
        return;
      }

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
      camera.position.set(0, 0, 7);

      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
      } catch {
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
      renderer.setClearColor(0x000000, 0);
      renderer.domElement.setAttribute('role', 'img');
      renderer.domElement.setAttribute('aria-label', '淡色三维学习空间背景');
      mount.appendChild(renderer.domElement);

      const orbit = new THREE.Group();
      scene.add(orbit);

      const material = new THREE.MeshBasicMaterial({
        color: 0x0a84ff,
        transparent: true,
        opacity: 0.24,
      });
      const accent = new THREE.MeshBasicMaterial({
        color: 0x30d158,
        transparent: true,
        opacity: 0.22,
      });
      const sphereGeometry = new THREE.SphereGeometry(1, 18, 18);

      const nodes = Array.from({ length: 24 }, (_, index) => {
        const radius = index % 5 === 0 ? 0.075 : 0.045;
        const mesh = new THREE.Mesh(sphereGeometry, index % 3 === 0 ? accent : material);
        const ring = index / 24;
        mesh.scale.setScalar(radius);
        mesh.position.set(
          Math.cos(ring * Math.PI * 2) * (2.8 + (index % 4) * 0.32),
          Math.sin(ring * Math.PI * 2) * (1.3 + (index % 6) * 0.12),
          -1.8 + (index % 7) * 0.42,
        );
        orbit.add(mesh);
        return mesh;
      });

      const lineMaterial = new THREE.LineBasicMaterial({
        color: 0x8e8e93,
        transparent: true,
        opacity: 0.14,
      });
      const points = nodes.map((node) => node.position);
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const constellation = new THREE.LineLoop(geometry, lineMaterial);
      orbit.add(constellation);

      const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
      let reduceMotion = mq.matches;
      const handleMotionPreference = (event) => {
        reduceMotion = event.matches;
      };
      mq.addEventListener?.('change', handleMotionPreference);

      let frame = 0;
      const resize = () => {
        const rect = mount.getBoundingClientRect();
        const width = Math.max(rect.width, 1);
        const height = Math.max(rect.height, 1);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
      };

      const animate = () => {
        if (!reduceMotion) {
          orbit.rotation.y += 0.0018;
          orbit.rotation.x = Math.sin(Date.now() * 0.00025) * 0.06;
        }
        renderer.render(scene, camera);
        frame = window.requestAnimationFrame(animate);
      };

      resize();
      window.addEventListener('resize', resize);
      animate();

      cleanupScene = () => {
        window.cancelAnimationFrame(frame);
        window.removeEventListener('resize', resize);
        mq.removeEventListener?.('change', handleMotionPreference);
        renderer.dispose();
        geometry.dispose();
        sphereGeometry.dispose();
        material.dispose();
        accent.dispose();
        lineMaterial.dispose();
        mount.replaceChildren();
      };
    }

    setupScene();

    return () => {
      disposed = true;
      cleanupScene();
    };
  }, []);

  return <div className="spatial-backdrop" ref={mountRef} />;
}
