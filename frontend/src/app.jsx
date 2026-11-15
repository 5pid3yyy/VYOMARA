
import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const HEALTH_INTERVAL = 15000;
const REQUEST_TIMEOUT = 120000;
const ANALYSIS_RADIUS_KM = 10;

function createPlanetTexture(planet) {
  const canvas = document.createElement("canvas");
  canvas.width = 2048;
  canvas.height = 1024;

  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas texture is unavailable.");

  const moon = planet === "Moon";
  const gradient = ctx.createLinearGradient(0, 0, 0, 1024);

  if (moon) {
    gradient.addColorStop(0, "#77736e");
    gradient.addColorStop(0.5, "#aaa49a");
    gradient.addColorStop(1, "#625e59");
  } else {
    gradient.addColorStop(0, "#9d5140");
    gradient.addColorStop(0.5, "#bd7351");
    gradient.addColorStop(1, "#71382f");
  }

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 2048, 1024);

  let seed = moon ? 12345 : 67890;

  function random() {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  }

  for (let i = 0; i < 1700; i++) {
    const x = random() * 2048;
    const y = random() * 1024;
    const r = 2 + random() * (moon ? 25 : 18);

    const crater = ctx.createRadialGradient(
      x - r * 0.2, y - r * 0.2, r * 0.1,
      x, y, r
    );

    crater.addColorStop(
      0,
      moon ? "rgba(20,20,20,.22)" : "rgba(65,20,15,.25)"
    );
    crater.addColorStop(
      0.65,
      moon ? "rgba(30,30,30,.09)" : "rgba(80,30,20,.12)"
    );
    crater.addColorStop(1, "rgba(255,255,255,.16)");

    ctx.fillStyle = crater;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  for (let i = 0; i < (moon ? 9 : 12); i++) {
    const x = random() * 2048;
    const y = random() * 1024;
    const r = 35 + random() * (moon ? 100 : 130);

    const region = ctx.createRadialGradient(
      x, y, r * 0.1, x, y, r
    );

    if (moon) {
      region.addColorStop(0, "rgba(45,44,43,.32)");
      region.addColorStop(0.7, "rgba(55,53,51,.20)");
    } else {
      region.addColorStop(0, "rgba(75,31,24,.25)");
      region.addColorStop(0.7, "rgba(95,40,28,.12)");
    }

    region.addColorStop(1, "rgba(55,53,51,0)");

    ctx.fillStyle = region;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function PlanetGlobe({ planet }) {
  const mountRef = useRef(null);
  const [globeError, setGlobeError] = useState("");

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer;
    let controls;
    let animationFrame;
    let resizeObserver;
    let geometry;
    let material;
    let texture;
    let atmosphereGeometry;
    let atmosphereMaterial;
    let active = true;

    try {
      const scene = new THREE.Scene();

      const camera = new THREE.PerspectiveCamera(
        40,
        Math.max(mount.clientWidth, 1) /
          Math.max(mount.clientHeight, 1),
        0.1,
        100
      );

      camera.position.set(0, 0, 5.8);

      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance"
      });

      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(mount.clientWidth || 1, mount.clientHeight || 1);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      mount.appendChild(renderer.domElement);

      scene.add(new THREE.AmbientLight(0xffffff, 1.15));

      const keyLight = new THREE.DirectionalLight(0xffffff, 2.5);
      keyLight.position.set(-4, 3, 5);
      scene.add(keyLight);

      const rimLight = new THREE.PointLight(0x4b9dff, 14, 12);
      rimLight.position.set(4, -2, -3);
      scene.add(rimLight);

      texture = createPlanetTexture(planet);
      geometry = new THREE.SphereGeometry(1.65, 96, 96);

      material = new THREE.MeshStandardMaterial({
        map: texture,
        roughness: 0.95,
        metalness: 0
      });

      const sphere = new THREE.Mesh(geometry, material);
      scene.add(sphere);

      atmosphereGeometry = new THREE.SphereGeometry(1.73, 64, 64);

      atmosphereMaterial = new THREE.MeshBasicMaterial({
        color: planet === "Moon" ? 0x8ca8d8 : 0xe58b65,
        transparent: true,
        opacity: 0.12,
        side: THREE.BackSide
      });

      scene.add(new THREE.Mesh(
        atmosphereGeometry,
        atmosphereMaterial
      ));

      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.045;
      controls.enablePan = false;
      controls.minDistance = 3.5;
      controls.maxDistance = 9;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.55;

      function animate() {
        if (!active) return;
        animationFrame = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      }

      animate();

      resizeObserver = new ResizeObserver(() => {
        if (!mount.clientWidth || !mount.clientHeight) return;

        camera.aspect = mount.clientWidth / mount.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(mount.clientWidth, mount.clientHeight);
      });

      resizeObserver.observe(mount);
      setGlobeError("");
    } catch (error) {
      console.error("Planet visualization error:", error);
      setGlobeError("3D visualization unavailable on this device.");
    }

    return () => {
      active = false;
      cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      controls?.dispose();
      geometry?.dispose();
      material?.dispose();
      texture?.dispose();
      atmosphereGeometry?.dispose();
      atmosphereMaterial?.dispose();
      renderer?.dispose();

      if (renderer?.domElement && mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [planet]);

  return (
    <div className="planet-canvas" ref={mountRef}>
      {globeError && <div className="globe-error">{globeError}</div>}
    </div>
  );
}

function OrbitalVisual() {
  return (
    <div className="orbital-visual" aria-label="Animated planetary orbit illustration">
      <div className="orbital-glow" />
      <div className="orbit orbit-one">
        <div className="orbit-dot dot-one" />
      </div>
      <div className="orbit orbit-two">
        <div className="orbit-dot dot-two" />
      </div>
      <div className="orbit orbit-three">
        <div className="orbit-dot dot-three" />
      </div>
      <div className="visual-planet">
        <div className="visual-planet-shade" />
        <div className="visual-planet-highlight" />
      </div>
      <div className="visual-crosshair crosshair-one" />
      <div className="visual-crosshair crosshair-two" />
      <div className="visual-label label-top">LUNAR / MARTIAN SYSTEM</div>
      <div className="visual-label label-bottom">TERRAIN ANALYSIS // ACTIVE</div>
      <div className="visual-coordinate">18° 38' N<br />77° 35' E</div>
    </div>
  );
}

function formatValue(value, digits = 2) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }

  const number = Number(value);

  return Number.isFinite(number)
    ? number.toLocaleString(undefined, {
        maximumFractionDigits: digits
      })
    : String(value);
}

function getSourceInfo(source = {}) {
  if (!source || typeof source !== "object") return [];

  return [
    source.provider,
    source.mission,
    source.instrument,
    source.dataset_id || source.dataset,
    source.product || source.model_type
  ].filter(Boolean).filter((value, index, array) =>
    array.indexOf(value) === index
  );
}

function getErrorMessage(data, status) {
  if (typeof data?.detail === "string") return data.detail;

  if (data?.detail) {
    try {
      return JSON.stringify(data.detail);
    } catch {
      return `Request failed with status ${status}.`;
    }
  }

  return data?.message || `Request failed with status ${status}.`;
}

const styles = `
:root {
  font-family: "Century Gothic", CenturyGothic, AppleGothic, sans-serif;
  color: #e8edf7;
  background: #070b13;
  font-synthesis: none;
}

* { box-sizing: border-box; }

html {
  scroll-behavior: smooth;
  scroll-padding-top: 25px;
}

body {
  margin: 0;
  min-width: 320px;
  background: #070b13;
  font-family: "Century Gothic", CenturyGothic, AppleGothic, sans-serif;
}

button, input, select { font: inherit; }
button { cursor: pointer; }

.vyomara {
  min-height: 100vh;
  position: relative;
  overflow-x: clip;
  background:
    radial-gradient(ellipse at 52% 38%, rgba(25,54,93,.22), transparent 48%),
    #070b13;
}

.stars, .stars:before, .stars:after {
  position: fixed;
  inset: 0;
  pointer-events: none;
  content: "";
  background-repeat: repeat;
  z-index: 0;
}

.stars {
  opacity: .65;
  background-image:
    radial-gradient(1px 1px at 20px 30px, #fff 99%, transparent),
    radial-gradient(1px 1px at 100px 140px, #fff 99%, transparent),
    radial-gradient(1px 1px at 190px 80px, #a9cfff 99%, transparent);
  background-size: 230px 190px;
  animation: starMove 90s linear infinite;
}

.stars:before {
  opacity: .45;
  background-image:
    radial-gradient(1.5px 1.5px at 60px 90px, #fff 99%, transparent),
    radial-gradient(1px 1px at 160px 30px, #b4d6ff 99%, transparent);
  background-size: 310px 270px;
  animation: starMove 130s linear infinite;
}

.stars:after {
  opacity: .3;
  background-image:
    radial-gradient(2px 2px at 80px 160px, #fff 99%, transparent),
    radial-gradient(1px 1px at 200px 60px, #fff 99%, transparent);
  background-size: 390px 350px;
  animation: starMove 180s linear infinite;
}

@keyframes starMove {
  from { transform: translateY(0); }
  to { transform: translateY(-350px); }
}

/* LANDING PAGE */

.landing-transition {
  height: 170vh;
  position: relative;
  z-index: 1;
}

.landing-sticky {
  position: sticky;
  top: 0;
  height: 100vh;
  height: 100svh;
  overflow: hidden;
}

.landing {
  position: relative;
  z-index: 1;
  height: 100vh;
  height: 100svh;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  max-width: 1600px;
  margin: auto;
  padding: 0 7%;
  transform-origin: 58% 48%;
  will-change: transform, opacity, filter;
  backface-visibility: hidden;
}

.landing-nav {
  height: 86px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(151,177,215,.15);
}

.landing-brand {
  display: flex;
  align-items: center;
  gap: 13px;
}

.brand-symbol {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border: 1px solid #76a9e9;
  color: #8dc4ff;
  border-radius: 11px;
  font-size: 22px;
  box-shadow: 0 0 22px rgba(75,145,240,.15);
}

.landing-brand-name {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 4px;
}

.landing-brand-sub {
  color: #8292a9;
  font-size: 9px;
  letter-spacing: 2px;
  margin-top: 4px;
}

.nav-tag {
  color: #8ba3c1;
  font-size: 10px;
  letter-spacing: 2px;
}

.landing-content {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1.1fr;
  align-items: center;
  gap: 30px;
  padding: 35px 0 55px;
}

.landing-copy {
  position: relative;
  z-index: 2;
}

.landing-eyebrow {
  color: #78b7ff;
  font-size: 10px;
  letter-spacing: 3px;
  margin-bottom: 22px;
}

.landing-copy h1 {
  font-size: clamp(42px, 6.2vw, 78px);
  font-weight: 500;
  letter-spacing: -3px;
  line-height: 1.08;
  margin: 0;
}

.landing-copy h1 span {
  color: #7fbaff;
  text-shadow: 0 0 35px rgba(86,157,232,.24);
}

.landing-description {
  max-width: 480px;
  color: #94a5bd;
  font-size: 13px;
  line-height: 2;
  margin: 25px 0 30px;
}

.landing-actions {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.explore-button {
  padding: 14px 22px;
  color: white;
  background: linear-gradient(100deg, #2569aa, #398ed4);
  border: 1px solid #5aa5e9;
  border-radius: 5px;
  font-size: 10px;
  letter-spacing: 1.5px;
  transition: .2s;
}

.explore-button:hover {
  filter: brightness(1.2);
  transform: translateY(-2px);
}

.landing-caption {
  color: #7187a3;
  font-size: 9px;
  letter-spacing: 1px;
}

.orbital-visual {
  width: min(100%, 610px);
  aspect-ratio: 1;
  position: relative;
  justify-self: center;
  display: grid;
  place-items: center;
  isolation: isolate;
}

.orbital-glow {
  position: absolute;
  width: 65%;
  height: 65%;
  border-radius: 50%;
  background: rgba(47,111,185,.14);
  filter: blur(65px);
  animation: glowPulse 5s ease-in-out infinite alternate;
}

@keyframes glowPulse {
  from { opacity: .45; transform: scale(.85); }
  to { opacity: 1; transform: scale(1.15); }
}

.visual-planet {
  position: absolute;
  width: 35%;
  aspect-ratio: 1;
  border-radius: 50%;
  overflow: hidden;
  background:
    radial-gradient(circle at 32% 28%, #b9c7d8 0%, #758ba6 22%, #344c6a 52%, #111d31 78%);
  box-shadow:
    inset -22px -12px 38px rgba(0,0,0,.75),
    inset 7px 5px 20px rgba(255,255,255,.25),
    0 0 45px rgba(91,151,214,.28);
  animation: planetFloat 7s ease-in-out infinite;
}

.visual-planet:before,
.visual-planet:after {
  content: "";
  position: absolute;
  border-radius: 50%;
  background: rgba(20,32,48,.22);
}

.visual-planet:before {
  width: 18%;
  height: 18%;
  top: 28%;
  left: 25%;
  box-shadow:
    44px 32px 0 -5px rgba(20,32,48,.24),
    -12px 70px 0 -7px rgba(20,32,48,.2),
    75px -12px 0 -9px rgba(20,32,48,.2);
}

.visual-planet:after {
  width: 130%;
  height: 130%;
  top: -15%;
  left: 35%;
  background: rgba(0,0,0,.26);
}

.visual-planet-shade {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: linear-gradient(110deg, transparent 20%, rgba(0,0,0,.45) 90%);
}

.visual-planet-highlight {
  position: absolute;
  top: 9%;
  left: 15%;
  width: 25%;
  height: 8%;
  border-radius: 50%;
  background: rgba(255,255,255,.17);
  filter: blur(10px);
  transform: rotate(-35deg);
}

@keyframes planetFloat {
  0%, 100% { transform: translateY(0) rotate(-5deg); }
  50% { transform: translateY(-13px) rotate(5deg); }
}

.orbit {
  position: absolute;
  width: 69%;
  height: 28%;
  border: 1px solid rgba(121,177,235,.4);
  border-radius: 50%;
  transform: rotate(-32deg);
}

.orbit-one { animation: orbitSpin 18s linear infinite; }

.orbit-two {
  width: 88%;
  height: 43%;
  border-color: rgba(121,177,235,.25);
  transform: rotate(52deg);
  animation: orbitSpinReverse 26s linear infinite;
}

.orbit-three {
  width: 96%;
  height: 61%;
  border-color: rgba(121,177,235,.13);
  transform: rotate(-65deg);
  animation: orbitSpin 38s linear infinite;
}

@keyframes orbitSpin {
  from { transform: rotate(-32deg); }
  to { transform: rotate(328deg); }
}

@keyframes orbitSpinReverse {
  from { transform: rotate(52deg); }
  to { transform: rotate(-308deg); }
}

.orbit-dot {
  position: absolute;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #a7d4ff;
  box-shadow: 0 0 15px #78baff, 0 0 28px rgba(120,186,255,.5);
}

.dot-one { top: 13%; left: 16%; }
.dot-two { top: 78%; left: 81%; width: 6px; height: 6px; }
.dot-three { top: 5%; left: 68%; width: 5px; height: 5px; }

.visual-crosshair {
  position: absolute;
  width: 12px;
  height: 12px;
  border: 1px solid rgba(139,192,248,.55);
  transform: rotate(45deg);
}

.crosshair-one { top: 19%; right: 15%; }
.crosshair-two { bottom: 17%; left: 15%; width: 7px; height: 7px; }

.visual-label {
  position: absolute;
  color: #7994b6;
  font-size: 8px;
  letter-spacing: 2px;
}

.label-top { top: 12%; left: 50%; transform: translateX(-50%); }
.label-bottom { bottom: 11%; left: 50%; transform: translateX(-50%); }

.visual-coordinate {
  position: absolute;
  right: 4%;
  bottom: 30%;
  color: #8cb8e8;
  font-size: 9px;
  line-height: 1.8;
  letter-spacing: 1px;
  opacity: .75;
}

.landing-bottom {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  padding: 20px 0;
  border-top: 1px solid rgba(151,177,215,.12);
  color: #607995;
  font-size: 9px;
  letter-spacing: 1.5px;
}

.scroll-indicator {
  position: absolute;
  bottom: 72px;
  left: 50%;
  transform: translateX(-50%);
  color: #7994b6;
  font-size: 9px;
  letter-spacing: 2px;
  animation: indicatorFloat 2s ease-in-out infinite;
}

@keyframes indicatorFloat {
  0%, 100% { transform: translate(-50%, 0); }
  50% { transform: translate(-50%, 7px); }
}

/* MAIN APPLICATION */

.app-shell {
  position: relative;
  z-index: 1;
  max-width: 1600px;
  margin: auto;
  padding: 0 38px 40px;
}

.app-divider {
  width: 100%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(115,165,220,.4), transparent);
  margin-bottom: 30px;
}

.topbar {
  height: 76px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(151,177,215,.15);
}

.brand {
  display: flex;
  align-items: center;
  gap: 13px;
}

.brand-mark {
  width: 39px;
  height: 39px;
  border: 1px solid #76a9e9;
  color: #8dc4ff;
  display: grid;
  place-items: center;
  border-radius: 11px;
  font-size: 21px;
  box-shadow: 0 0 22px rgba(75,145,240,.15);
}

.brand-name {
  font-weight: 700;
  letter-spacing: 3px;
  font-size: 19px;
}

.brand-sub {
  color: #8292a9;
  font-size: 9px;
  letter-spacing: 2px;
  margin-top: 4px;
}

.top-right {
  display: flex;
  gap: 18px;
  align-items: center;
}

.status {
  color: #8ad5b1;
  font-size: 10px;
  letter-spacing: 1px;
}

.status:before {
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  background: #54d59b;
  border-radius: 50%;
  margin-right: 8px;
  box-shadow: 0 0 10px #54d59b;
}

.status.offline { color: #e99a9a; }
.status.offline:before { background: #df7777; box-shadow: 0 0 10px #df7777; }
.status.checking { color: #e6b078; }
.status.checking:before { background: #e6b078; box-shadow: 0 0 10px #e6b078; }

.hero {
  display: flex;
  justify-content: space-between;
  align-items: end;
  padding: 37px 0 27px;
}

.eyebrow {
  color: #78b7ff;
  font-size: 10px;
  letter-spacing: 3px;
  margin-bottom: 12px;
}

.hero h1 {
  font-size: clamp(27px, 4vw, 43px);
  letter-spacing: -1.8px;
  margin: 0;
  font-weight: 500;
}

.hero p {
  color: #8b9bb2;
  font-size: 13px;
  margin: 12px 0 0;
  line-height: 1.7;
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(300px, .85fr);
  gap: 19px;
}

.panel {
  background: linear-gradient(145deg, rgba(17,27,43,.94), rgba(10,17,29,.96));
  border: 1px solid rgba(125,157,200,.18);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 12px 50px rgba(0,0,0,.18);
}

.panel-heading {
  padding: 17px 20px;
  border-bottom: 1px solid rgba(125,157,200,.13);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.panel-heading h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 1.3px;
  font-weight: 600;
}

.panel-heading span {
  color: #778ba7;
  font-size: 9px;
  letter-spacing: 1px;
}

.globe-area {
  min-height: 435px;
  position: relative;
  display: grid;
  place-items: center;
  background: radial-gradient(ellipse at center, rgba(35,75,120,.17), transparent 65%);
}

.planet-canvas {
  width: 100%;
  height: 435px;
  position: relative;
  touch-action: pan-y;
}

.globe-error {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 25px;
  color: #e6b078;
  text-align: center;
  font-size: 12px;
}

.globe-label {
  position: absolute;
  top: 20px;
  left: 20px;
  color: #7e94b1;
  font-size: 10px;
  letter-spacing: 1px;
  pointer-events: none;
  z-index: 1;
}

.globe-bottom {
  position: absolute;
  bottom: 18px;
  left: 20px;
  right: 20px;
  display: flex;
  justify-content: space-between;
  color: #778ba7;
  font-size: 9px;
  letter-spacing: 1px;
  pointer-events: none;
  z-index: 1;
}

.planet-switch {
  display: flex;
  gap: 8px;
}

.planet-switch button {
  background: #101d30;
  border: 1px solid #2b405b;
  color: #8799b1;
  border-radius: 6px;
  padding: 8px 13px;
  font-size: 11px;
  transition: .2s;
}

.planet-switch button.active {
  background: rgba(55,126,207,.18);
  color: #a8d2ff;
  border-color: #559ce8;
}

.control-panel { padding-bottom: 19px; }
.control-content { padding: 20px; }
.field { margin-bottom: 19px; }

.field label {
  display: block;
  font-size: 10px;
  color: #92a3ba;
  letter-spacing: 1px;
  margin-bottom: 9px;
}

.field input, .field select {
  width: 100%;
  padding: 11px 12px;
  border-radius: 6px;
  background: #0a1422;
  border: 1px solid #293a51;
  color: #dce9f9;
  outline: none;
  font-size: 12px;
}

.field input:focus, .field select:focus {
  border-color: #5798dc;
}

.coordinate-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

/* FIND ANALOGUES BUTTON AND FIXED RADIUS NOTE */

.analyze-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 5px;
}

.analyze {
  flex: 1;
  min-width: 0;
  background: linear-gradient(100deg, #2569aa, #398ed4);
  border: 1px solid #5aa5e9;
  border-radius: 7px;
  padding: 14px 10px;
  color: white;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
  transition: .2s;
}

.analyze:hover { filter: brightness(1.15); }
.analyze:disabled { opacity: .55; cursor: not-allowed; }

.radius-note {
  flex-shrink: 0;
  color: #8eacd0;
  font-size: 9px;
  letter-spacing: .7px;
  white-space: nowrap;
}

.note {
  color: #657b98;
  font-size: 9px;
  line-height: 1.6;
  margin-top: 12px;
}

.lower-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 19px;
  margin-top: 19px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 9px;
  padding: 17px;
}

.metric {
  padding: 14px 11px;
  background: rgba(7,15,26,.72);
  border: 1px solid rgba(116,150,194,.13);
  border-radius: 8px;
}

.metric small {
  color: #7d91ad;
  font-size: 9px;
}

.metric strong {
  display: block;
  margin-top: 10px;
  font-size: 16px;
  font-weight: 500;
}

.metric em {
  display: block;
  margin-top: 5px;
  font-style: normal;
  color: #6f88a8;
  font-size: 9px;
}

.result-content {
  padding: 19px;
  color: #8598b3;
  font-size: 11px;
  line-height: 1.8;
}

.result-message {
  border-left: 2px solid #e2a35d;
  background: rgba(226,163,93,.07);
  padding: 12px;
  color: #d7b58b;
  overflow-wrap: anywhere;
}

.result-message.error {
  border-color: #df7777;
  background: rgba(223,119,119,.07);
  color: #e9a1a1;
}

.results-list {
  display: grid;
  gap: 13px;
}

.result-card {
  padding: 15px;
  border: 1px solid rgba(116,150,194,.17);
  border-radius: 8px;
  background: rgba(7,15,26,.65);
}

.result-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.result-rank {
  color: #7faee2;
  font-size: 9px;
  letter-spacing: 1px;
  margin-bottom: 7px;
}

.result-name {
  color: #e5edf8;
  font-size: 15px;
  font-weight: 600;
}

.result-country {
  color: #8194af;
  font-size: 10px;
  margin-top: 4px;
}

.score {
  color: #8ed5b4;
  font-size: 18px;
  white-space: nowrap;
}

.score-label {
  color: #6f88a8;
  font-size: 8px;
  text-align: right;
  margin-top: 4px;
}

.result-coordinates {
  color: #8194af;
  font-size: 9px;
  margin-top: 13px;
}

.descriptor-heading {
  color: #8ea5c2;
  font-size: 9px;
  letter-spacing: 1px;
  margin: 16px 0 8px;
}

.descriptor-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 7px;
}

.descriptor {
  background: rgba(17,31,49,.7);
  border-radius: 5px;
  padding: 9px;
  min-width: 0;
}

.descriptor span {
  display: block;
  color: #7288a5;
  font-size: 9px;
}

.descriptor strong {
  display: block;
  color: #d2dfef;
  font-size: 11px;
  margin-top: 5px;
  overflow-wrap: anywhere;
}

.comparison-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px;
}

.comparison-cell {
  background: rgba(17,31,49,.7);
  border-radius: 5px;
  padding: 9px;
  min-width: 0;
}

.comparison-cell small {
  display: block;
  color: #7288a5;
  font-size: 8px;
  letter-spacing: .5px;
}

.comparison-cell strong {
  display: block;
  color: #d2dfef;
  font-size: 11px;
  margin-top: 5px;
  overflow-wrap: anywhere;
}

.source-info {
  color: #7187a3;
  font-size: 9px;
  line-height: 1.7;
  margin-top: 12px;
  overflow-wrap: anywhere;
}

.source-info div + div { margin-top: 3px; }

.results-disclaimer {
  color: #8194af;
  font-size: 9px;
  line-height: 1.7;
  margin-top: 15px;
  padding-top: 12px;
  border-top: 1px solid rgba(125,157,200,.13);
}

.footer {
  border-top: 1px solid rgba(125,157,200,.14);
  margin-top: 28px;
  padding: 17px 0;
  display: flex;
  justify-content: space-between;
  color: #60718a;
  font-size: 9px;
  letter-spacing: .5px;
}

.footer strong { color: #91a9c7; }

@media(max-width: 900px) {
  .landing { padding: 0 5%; }
  .landing-content {
    grid-template-columns: 1fr;
    text-align: center;
    padding-top: 30px;
    padding-bottom: 25px;
    gap: 0;
  }
  .landing-copy { order: 1; }
  .orbital-visual {
    order: 0;
    width: min(55%, 330px);
  }
  .landing-description { margin-left: auto; margin-right: auto; }
  .landing-actions { justify-content: center; }
  .scroll-indicator { display: none; }
  .layout { grid-template-columns: 1fr; }
  .lower-grid { grid-template-columns: 1fr; }
  .landing { transform-origin: 50% 45%; }
}

@media(max-width: 560px) {
  .landing { padding: 0 18px; }
  .landing-nav { height: 70px; }
  .landing-brand-name { font-size: 16px; }
  .nav-tag { display: none; }
  .landing-content { padding-top: 18px; padding-bottom: 15px; }
  .landing-copy h1 { font-size: 39px; letter-spacing: -2px; }
  .landing-description { font-size: 11px; line-height: 1.7; margin: 15px auto 18px; }
  .landing-eyebrow { font-size: 8px; margin-bottom: 12px; }
  .orbital-visual { width: min(65%, 245px); }
  .landing-bottom { font-size: 7px; gap: 15px; }
  .landing-caption { display: none; }
  .app-shell { padding: 0 14px 25px; }
  .topbar { height: 65px; }
  .brand-name { font-size: 16px; }
  .status { display: none; }
  .hero { padding-top: 28px; }
  .globe-area, .planet-canvas {
    height: 340px;
    min-height: 340px;
  }
  .metric-grid { grid-template-columns: 1fr 1fr; }
  .footer { flex-direction: column; gap: 9px; }

  .analyze-row {
    gap: 8px;
  }

  .radius-note {
    font-size: 8px;
  }
}

/* Reduced-motion accessibility */
@media(prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }

  *, *:before, *:after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
  }

  .landing-transition { height: 100vh; }

  .landing-sticky {
    position: relative;
    height: auto;
  }

  .landing {
    transform: none !important;
    opacity: 1 !important;
    filter: none !important;
  }
}
`;

function ResultCard({ item, index, planet }) {
  const descriptors = item.descriptors || {};
  const targetDescriptors = item.target_descriptors || {};
  const sources = item.data_sources || {};

  const candidateSource = getSourceInfo(sources.candidate);
  const targetSource = getSourceInfo(sources.target);

  const metrics = [
    ["Mean elevation", descriptors.elevation_mean, "m"],
    ["Elevation range", descriptors.relief, "m"],
    ["Mean slope", descriptors.slope_mean, "°"],
    ["Terrain roughness", descriptors.roughness, "m"]
  ];

  const comparisonMetrics = [
    ["Mean elevation", "elevation_mean", "m"],
    ["Relief", "relief", "m"],
    ["Mean slope", "slope_mean", "°"],
    ["Roughness", "roughness", "m"]
  ];

  const score = Number(item.similarity_score);
  const hasTargetComparison = comparisonMetrics.some(
    ([, key]) =>
      targetDescriptors[key] !== null &&
      targetDescriptors[key] !== undefined
  );

  return (
    <article className="result-card">
      <div className="result-card-top">
        <div>
          <div className="result-rank">RANK {index + 1}</div>
          <div className="result-name">
            {item.location_name || "Unnamed region"}
          </div>
          <div className="result-country">
            {item.country || "Location unavailable"}
          </div>
        </div>

        <div>
          <div className="score">
            {Number.isFinite(score) ? score.toFixed(2) : "N/A"}
          </div>
          <div className="score-label">SIMILARITY INDEX</div>
        </div>
      </div>

      <div className="result-coordinates">
        LAT {formatValue(item.latitude ?? item.lat, 4)}°
        &nbsp; / &nbsp;
        LON {formatValue(item.longitude ?? item.lon, 4)}°
      </div>

      <div className="descriptor-heading">EARTH TERRAIN MEASUREMENTS</div>

      <div className="descriptor-grid">
        {metrics.map(([label, value, unit]) => (
          <div className="descriptor" key={label}>
            <span>{label}</span>
            <strong>
              {formatValue(value)} {value == null ? "" : unit}
            </strong>
          </div>
        ))}
      </div>

      {hasTargetComparison && (
        <>
          <div className="descriptor-heading">
            {planet.toUpperCase()} TARGET / EARTH COMPARISON
          </div>

          <div className="comparison-grid">
            <div className="comparison-cell">
              <small>{planet.toUpperCase()} TARGET</small>
              {comparisonMetrics.map(([label, key, unit]) => (
                <strong key={key}>
                  {label}: {formatValue(targetDescriptors[key])}
                  {targetDescriptors[key] == null ? "" : ` ${unit}`}
                </strong>
              ))}
            </div>

            <div className="comparison-cell">
              <small>EARTH CANDIDATE</small>
              {comparisonMetrics.map(([label, key, unit]) => (
                <strong key={key}>
                  {label}: {formatValue(descriptors[key])}
                  {descriptors[key] == null ? "" : ` ${unit}`}
                </strong>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="source-info">
        {targetSource.length > 0 && (
          <div>Target data: {targetSource.join(" · ")}</div>
        )}
        {candidateSource.length > 0 && (
          <div>Earth data: {candidateSource.join(" · ")}</div>
        )}
        {targetSource.length === 0 && candidateSource.length === 0 && (
          <div>Data provenance was not included in this API response.</div>
        )}
      </div>
    </article>
  );
}

export default function App() {
  const [planet, setPlanet] = useState("Moon");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const [apiStatus, setApiStatus] = useState("CHECKING");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const requestRef = useRef(null);
  const transitionRef = useRef(null);

  useEffect(() => {
    const stage = transitionRef.current;
    if (!stage) return;

    const landing = stage.querySelector(".landing");
    if (!landing) return;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    );

    if (reducedMotion.matches) return;

    let frame = 0;

    function updateTransition() {
      cancelAnimationFrame(frame);

      frame = requestAnimationFrame(() => {
        const rect = stage.getBoundingClientRect();

        const distance = Math.max(
          stage.offsetHeight - window.innerHeight,
          1
        );

        const progress = Math.min(
          1,
          Math.max(0, -rect.top / distance)
        );

        const eased = progress * progress * (3 - 2 * progress);

        const zoom = 1 + eased * 1.55;
        const opacity = 1 - Math.pow(progress, 1.25);
        const blur = eased * 7;

        landing.style.transform = `scale(${zoom})`;
        landing.style.opacity = String(opacity);
        landing.style.filter = `blur(${blur}px)`;

        landing.style.pointerEvents =
          progress > 0.88 ? "none" : "auto";

        landing.setAttribute(
          "aria-hidden",
          progress > 0.98 ? "true" : "false"
        );
      });
    }

    window.addEventListener("scroll", updateTransition, {
      passive: true
    });

    window.addEventListener("resize", updateTransition);

    updateTransition();

    return () => {
      window.removeEventListener("scroll", updateTransition);
      window.removeEventListener("resize", updateTransition);
      cancelAnimationFrame(frame);
    };
  }, []);

  function enterExplorer() {
    const target = document.getElementById("explorer");
    if (!target) return;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    target.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start"
    });
  }

  useEffect(() => {
    let cancelled = false;
    let activeController = null;

    async function checkAPI() {
      activeController?.abort();
      activeController = new AbortController();

      try {
        const response = await fetch(`${API}/api/health`, {
          signal: activeController.signal
        });

        if (!response.ok) throw new Error("API health check failed");

        const data = await response.json();

        if (!cancelled) {
          const status = String(data.status || "").toLowerCase();

          setApiStatus(
            status === "healthy" || status === "online"
              ? "ONLINE"
              : "CONNECTED"
          );
        }
      } catch {
        if (!cancelled) setApiStatus("OFFLINE");
      }
    }

    checkAPI();
    const interval = setInterval(checkAPI, HEALTH_INTERVAL);

    return () => {
      cancelled = true;
      clearInterval(interval);
      activeController?.abort();
    };
  }, []);

  useEffect(() => {
    return () => requestRef.current?.abort();
  }, []);

  function changePlanet(value) {
    requestRef.current?.abort();
    requestRef.current = null;

    setLoading(false);
    setPlanet(value);
    setLat("");
    setLon("");
    setResult(null);
    setError("");
  }

  async function discover() {
    const latitude = Number(lat);
    const longitude = Number(lon);

    if (
      lat.trim() === "" ||
      !Number.isFinite(latitude) ||
      latitude < -90 ||
      latitude > 90
    ) {
      setError("Latitude must be between -90 and 90 degrees.");
      return;
    }

    if (
      lon.trim() === "" ||
      !Number.isFinite(longitude) ||
      longitude < -180 ||
      longitude > 180
    ) {
      setError("Longitude must be between -180 and 180 degrees.");
      return;
    }

    requestRef.current?.abort();

    const controller = new AbortController();
    requestRef.current = controller;

    const timeout = setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT
    );

    setLoading(true);
    setError("");
    setResult(null);

    const params = new URLSearchParams({
      planet: planet.toLowerCase(),
      lat: String(latitude),
      lon: String(longitude),
      radius: String(ANALYSIS_RADIUS_KM),
      mode: "scientific"
    });

    try {
      const response = await fetch(
        `${API}/api/discover?${params}`,
        { signal: controller.signal }
      );

      let data;

      try {
        data = await response.json();
      } catch {
        throw new Error(
          `The API returned an unreadable response (HTTP ${response.status}).`
        );
      }

      if (!response.ok) {
        throw new Error(getErrorMessage(data, response.status));
      }

      if (!Array.isArray(data)) {
        throw new Error(
          "Unexpected API response. Expected a list of candidate regions."
        );
      }

      const ranked = [...data].sort((a, b) => {
        const scoreA = Number(a.similarity_score);
        const scoreB = Number(b.similarity_score);

        const validA = Number.isFinite(scoreA);
        const validB = Number.isFinite(scoreB);

        if (!validA && !validB) return 0;
        if (!validA) return 1;
        if (!validB) return -1;

        return scoreB - scoreA;
      });

      setResult({
        total: data.length,
        topThree: ranked.slice(0, 3),
        planet,
        latitude,
        longitude,
        radius: ANALYSIS_RADIUS_KM
      });

      if (data.length === 0) {
        setError("No candidate regions were returned for this analysis.");
      }
    } catch (err) {
      if (err.name === "AbortError") {
        setError(
          "The analysis timed out or was cancelled. Check the backend and try again."
        );
      } else {
        setError(err.message || "Unable to contact the VYOMARA API.");
      }
    } finally {
      clearTimeout(timeout);

      if (requestRef.current === controller) {
        requestRef.current = null;
        setLoading(false);
      }
    }
  }

  const topThree = result?.topThree || [];

  const statusLabel =
    apiStatus === "ONLINE"
      ? "ENGINE ONLINE"
      : apiStatus === "OFFLINE"
        ? "ENGINE OFFLINE"
        : apiStatus === "CHECKING"
          ? "CHECKING CONNECTION"
          : "ENGINE CONNECTED";

  return (
    <>
      <style>{styles}</style>

      <div className="vyomara">
        <div className="stars" />

        <div
          className="landing-transition"
          ref={transitionRef}
        >
          <div className="landing-sticky">
            <section className="landing">
              <nav className="landing-nav">
                <div className="landing-brand">
                  <div className="brand-symbol">✧</div>
                  <div>
                    <div className="landing-brand-name">VYOMARA</div>
                    <div className="landing-brand-sub">
                      PLANETARY ANALOGUE DISCOVERY
                    </div>
                  </div>
                </div>

                <div className="nav-tag">MOON · MARS · EARTH</div>
              </nav>

              <div className="landing-content">
                <div className="landing-copy">
                  <div className="landing-eyebrow">
                    A NEW PERSPECTIVE ON PLANETARY EXPLORATION
                  </div>

                  <h1>
                    Worlds apart.
                    <br />
                    <span>Terrain connected.</span>
                  </h1>

                  <p className="landing-description">
                    Explore the Moon and Mars through the landscapes of Earth.
                    VYOMARA analyses planetary terrain and identifies
                    terrestrial environments with comparable characteristics.
                  </p>

                  <div className="landing-actions">
                    <button
                      className="explore-button"
                      onClick={enterExplorer}
                    >
                      ENTER EXPLORER &nbsp; ↘
                    </button>

                    <span className="landing-caption">
                      GIS · TERRAIN METRICS · ANALOGUE DISCOVERY
                    </span>
                  </div>
                </div>

                <OrbitalVisual />
              </div>

              <div className="landing-bottom">
                <span>PLANETARY TERRAIN INTELLIGENCE</span>
                <span>AN EXPLORATION OF EARTH ANALOGUES</span>
              </div>

              <div className="scroll-indicator">
                SCROLL TO EXPLORE &nbsp; ↓
              </div>
            </section>
          </div>
        </div>

        <div id="explorer" className="app-shell">
          <div className="app-divider" />

          <header className="topbar">
            <div className="brand">
              <div className="brand-mark">✧</div>
              <div>
                <div className="brand-name">VYOMARA</div>
                <div className="brand-sub">
                  PLANETARY ANALOGUE DISCOVERY
                </div>
              </div>
            </div>

            <div className="top-right">
              <span
                className={`status ${
                  apiStatus === "OFFLINE"
                    ? "offline"
                    : apiStatus === "CHECKING"
                      ? "checking"
                      : ""
                }`}
              >
                {statusLabel}
              </span>
            </div>
          </header>

          <section className="hero">
            <div>
              <div className="eyebrow">
                PLANETARY TERRAIN ANALYSIS
              </div>

              <h1>
                Explore worlds.
                <br />
                Discover analogues.
              </h1>

              <p>
                Compare lunar and Martian terrain with
                environments found on Earth.
              </p>
            </div>
          </section>

          <main className="layout">
            <section className="panel">
              <div className="panel-heading">
                <h3>PLANETARY VISUALIZATION</h3>

                <div className="planet-switch">
                  <button
                    className={planet === "Moon" ? "active" : ""}
                    onClick={() => changePlanet("Moon")}
                    aria-pressed={planet === "Moon"}
                  >
                    ☾ MOON
                  </button>

                  <button
                    className={planet === "Mars" ? "active" : ""}
                    onClick={() => changePlanet("Mars")}
                    aria-pressed={planet === "Mars"}
                  >
                    ♂ MARS
                  </button>
                </div>
              </div>

              <div className="globe-area">
                <div className="globe-label">
                  {planet.toUpperCase()} / ILLUSTRATIVE 3D MODEL
                </div>

                <PlanetGlobe planet={planet} />

                <div className="globe-bottom">
                  <span>{planet.toUpperCase()}</span>
                  <span>ROTATE TO EXPLORE</span>
                </div>
              </div>
            </section>

            <section className="panel control-panel">
              <div className="panel-heading">
                <h3>ANALYSIS SETTINGS</h3>
                <span>INPUT</span>
              </div>

              <div className="control-content">
                <div className="field">
                  <label>PLANETARY BODY</label>

                  <select
                    value={planet}
                    onChange={e => changePlanet(e.target.value)}
                  >
                    <option value="Moon">Moon</option>
                    <option value="Mars">Mars</option>
                  </select>
                </div>

                <div className="field">
                  <label>REFERENCE COORDINATES</label>

                  <div className="coordinate-grid">
                    <div>
                      <label htmlFor="latitude">LATITUDE (°)</label>
                      <input
                        id="latitude"
                        type="number"
                        step="0.01"
                        min="-90"
                        max="90"
                        placeholder="Enter latitude"
                        value={lat}
                        onChange={e => setLat(e.target.value)}
                      />
                    </div>

                    <div>
                      <label htmlFor="longitude">LONGITUDE (°)</label>
                      <input
                        id="longitude"
                        type="number"
                        step="0.01"
                        min="-180"
                        max="180"
                        placeholder="Enter longitude"
                        value={lon}
                        onChange={e => setLon(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                <div className="analyze-row">
                  <button
                    className="analyze"
                    onClick={discover}
                    disabled={loading || apiStatus === "OFFLINE"}
                  >
                    {loading
                      ? "ANALYSING TERRAIN..."
                      : "↗  FIND EARTH ANALOGUES"}
                  </button>

                  <span className="radius-note">
                    FIXED RADIUS: 10 KM
                  </span>
                </div>

                <div className="note">
                  Results are ranked using terrain similarity
                  measurements from the available Earth candidates.
                  The 3D model is illustrative and is not a terrain DEM.
                </div>
              </div>
            </section>
          </main>

          <section className="lower-grid">
            <div className="panel">
              <div className="panel-heading">
                <h3>ANALYSIS INFORMATION</h3>
                <span>CONFIGURATION</span>
              </div>

              <div className="metric-grid">
                <div className="metric">
                  <small>PLANET</small>
                  <strong>{planet}</strong>
                  <em>
                    {planet === "Moon" ? "LOLA dataset" : "MOLA dataset"}
                  </em>
                </div>

                <div className="metric">
                  <small>SEARCH RADIUS</small>
                  <strong>{ANALYSIS_RADIUS_KM} km</strong>
                  <em>Analysis window</em>
                </div>

                <div className="metric">
                  <small>API STATUS</small>
                  <strong
                    style={{
                      color:
                        apiStatus === "ONLINE"
                          ? "#79d9ae"
                          : apiStatus === "OFFLINE"
                            ? "#e99a9a"
                            : "#e6b078"
                    }}
                  >
                    {apiStatus}
                  </strong>
                  <em>Backend connection</em>
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-heading">
                <h3>EARTH ANALOGUE RESULTS</h3>
                <span>
                  {result
                    ? `${topThree.length} SHOWN`
                    : "AWAITING ANALYSIS"}
                </span>
              </div>

              <div className="result-content">
                {!result && !error && !loading && (
                  <p>
                    Select a planetary location and run the analysis
                    to view the closest matching Earth regions.
                  </p>
                )}

                {loading && (
                  <p>
                    Analysing terrain data and ranking Earth regions...
                  </p>
                )}

                {error && (
                  <div className="result-message error" role="alert">
                    <strong>ANALYSIS NOT COMPLETED</strong>
                    <br />
                    {error}
                  </div>
                )}

                {result && topThree.length > 0 && (
                  <>
                    <div className="results-list">
                      {topThree.map((item, index) => (
                        <ResultCard
                          key={
                            item.id ||
                            `${item.location_name}-${item.latitude}-${index}`
                          }
                          item={item}
                          index={index}
                          planet={result.planet}
                        />
                      ))}
                    </div>

                    <div className="results-disclaimer">
                      Showing the top {topThree.length} matches from
                      {" "}{result.total} evaluated candidate regions.
                      This is not an exhaustive global ranking.
                      Similarity scores are comparative indices,
                      not probabilities or confidence levels.
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>

          <footer className="footer">
            <span>
              <strong>VYOMARA</strong> · PLANETARY ANALOGUE DISCOVERY
            </span>

            <span>
              LUNAR & MARTIAN TERRAIN COMPARISON
            </span>
          </footer>
        </div>
      </div>
    </>
  );
}
