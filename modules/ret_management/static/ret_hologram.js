/**
 * RET Management site hologram — three.js 3D view.
 *
 * Default camera is a top-down view tilted 30° so the mast sits in the centre
 * with lobes readable in perspective. Each sector is a 3D power lobe (cos^n
 * pattern). Electrical RET tilt is degrees below the sector horizon plane —
 * lobe pointing and ground reach both follow that value. Coverage length is
 * further scaled by band (L900/2G > L1800 > L2100/3G). AAU Left/Right use
 * 30° HPBW half-beams. Azimuth comes from PrimeNet metadata.
 *
 * three.min.js is vendored under static/vendor/ for intranet use (no CDN).
 */
(function (global) {
    'use strict';

    const TECH_COLORS = {
        '2G': [242, 177, 52],
        '3G': [167, 119, 227],
        '4G': [58, 190, 232],
        '4G-FDD': [58, 190, 232],   // metadata inventory fallback
        '4G-TDD': [46, 204, 175],
        '4G-AAU-Left': [80, 170, 255],
        '4G-AAU-Right': [40, 140, 230],
        '4G-AAU': [60, 155, 245],
        '4G-L1800+': [30, 120, 200],
        'Not Used': [120, 120, 130],
        '5G': [236, 100, 190],      // metadata inventory only
    };
    const TECH_RANK = [
        '4G-AAU-Left', '4G-AAU-Right', '4G-AAU', '4G-L1800+',
        '4G-TDD', '4G', '4G-FDD', '5G', '3G', '2G', 'Not Used',
    ];
    /** Relative coverage reach by tech / band (L900 largest → L2100 smallest). */
    const BAND_COVERAGE = {
        '2G': 1.0,            // L900
        '4G': 0.72,           // L1800
        '4G-FDD': 0.72,
        '4G-L1800+': 0.78,    // capacity L1800+
        '4G-TDD': 0.70,
        '4G-AAU-Left': 0.70,
        '4G-AAU-Right': 0.70,
        '4G-AAU': 0.70,
        '3G': 0.50,           // L2100
        '5G': 0.48,
        'Not Used': 0.32,
    };
    const DEFAULT_COLOR = [110, 196, 240];
    const EDIT_COLOR = [247, 181, 56];
    const HPBW_DEG = 60;
    const AAU_HPBW_DEG = 30;
    const DEFAULT_PITCH_DEG = 30;
    const MIN_TILT_FOR_DISTANCE = 0.5;
    const DEFAULT_TILT_DEG = 4;
    /**
     * Working ground-reach window for the hologram (metres).
     * Geometry is still h/tan(tilt); result is clamped here until a future
     * performance/TA pipeline can supply measured cell distance.
     */
    const MIN_GROUND_DISTANCE_M = 100;
    const MAX_GROUND_DISTANCE_M = 1000;
    /** Scene length at the 100 m / 1000 m ends of that window (before band factor). */
    const SCENE_LENGTH_AT_MIN_M = 55;
    const SCENE_LENGTH_AT_MAX_M = 260;
    const CAMERA_BASE_DIST = 330;
    /**
     * Self-supporting lattice tower (same language as portal_tower.js):
     * tapered 4-leg lattice + pipe mast + antenna panels + ground shelter.
     */
    const LATTICE_H = 36;
    const LATTICE_SEGMENTS = 9;
    const MAST_PIPE_TOP = LATTICE_H + 14;
    const BEACON_Y = MAST_PIPE_TOP + 1.2;
    /** Antenna panel box — lobes originate at the outward face midpoint. */
    const PANEL_WIDTH = 3.2;
    const PANEL_HEIGHT = 12;
    const PANEL_DEPTH = 1.2;
    const PANEL_MOUNT_RADIUS = 4.2;
    const PANEL_CENTER_Y = LATTICE_H + 7;
    const PANEL_FACE_RADIUS = PANEL_MOUNT_RADIUS + PANEL_DEPTH / 2;
    /** @deprecated alias kept for any leftover references */
    const MAST_TOP_Y = PANEL_CENTER_Y;
    /** Mechanical downtilt weight vs RET (metadata mtilt is 3× as effective). */
    const MECH_TILT_WEIGHT = 3;
    /**
     * Analytical pattern detail (reference polar plot ratios):
     * main = 1.0, back ≈ 0.55 @ 180°, two sides ≈ 0.20 @ ±90°.
     */
    const BACK_LOBE_REL_LENGTH = 0.55;
    const SIDE_LOBE_REL_LENGTH = 0.20;
    const SIDE_LOBE_AZ_OFFSET = 90;
    const BACK_LOBE_AZ_OFFSET = 180;

    function latticeHalfW(y) {
        const t = Math.max(0, 1 - y / LATTICE_H);
        return 2.0 + 10.5 * Math.pow(t, 1.18);
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function techColor(technologies) {
        const list = Array.isArray(technologies) ? technologies : [];
        for (const tech of TECH_RANK) {
            if (list.includes(tech)) return TECH_COLORS[tech];
        }
        return DEFAULT_COLOR;
    }

    function primaryTech(sector) {
        if (sector && sector.technology && sector.technology !== 'Unknown') {
            return sector.technology;
        }
        const list = (sector && sector.technologies) || [];
        return list[0] || '';
    }

    function bandCoverageFactor(tech) {
        if (tech && Object.prototype.hasOwnProperty.call(BAND_COVERAGE, tech)) {
            return BAND_COVERAGE[tech];
        }
        return 0.7;
    }

    function toRadians(deg) {
        return (deg * Math.PI) / 180;
    }

    /**
     * Combined downtilt for pointing / reach: RET + 3 × mechanical (metadata).
     */
    function effectiveTiltDeg(retTilt, mechTilt) {
        const ret = Number.isFinite(retTilt) ? Math.abs(retTilt) : DEFAULT_TILT_DEG;
        const mech = Number.isFinite(mechTilt) ? mechTilt : 0;
        return Math.max(MIN_TILT_FOR_DISTANCE, ret + MECH_TILT_WEIGHT * mech);
    }

    /** Ground reach (m) for electrical downtilt under the horizon plane. */
    function groundDistance(heightM, tiltDeg) {
        const height = Number.isFinite(heightM) && heightM > 0 ? heightM : 25;
        const raw = Number.isFinite(tiltDeg) ? Math.abs(tiltDeg) : DEFAULT_TILT_DEG;
        const tilt = Math.max(MIN_TILT_FOR_DISTANCE, raw);
        const distance = height / Math.tan(toRadians(tilt));
        return clamp(distance, MIN_GROUND_DISTANCE_M, MAX_GROUND_DISTANCE_M);
    }

    /**
     * Map clamped reach [100, 1000] m linearly into scene units, then apply
     * band coverage so L900 stays longer than L2100 inside that window.
     */
    function lobeLength(heightM, tiltDeg, tech) {
        const reachM = groundDistance(heightM, tiltDeg);
        const t = (reachM - MIN_GROUND_DISTANCE_M)
            / (MAX_GROUND_DISTANCE_M - MIN_GROUND_DISTANCE_M);
        const base = SCENE_LENGTH_AT_MIN_M
            + clamp(t, 0, 1) * (SCENE_LENGTH_AT_MAX_M - SCENE_LENGTH_AT_MIN_M);
        return base * bandCoverageFactor(tech);
    }

    function formatDegrees(value) {
        if (!Number.isFinite(value)) return '—';
        const rounded = Math.round(value * 10) / 10;
        return Number.isInteger(rounded) ? `${rounded}°` : `${rounded.toFixed(1)}°`;
    }

    function formatDistance(metres) {
        if (!Number.isFinite(metres)) return '—';
        if (metres >= 1000) return `${(metres / 1000).toFixed(2)} km`;
        return `${Math.round(metres)} m`;
    }

    function escapeHtml(value) {
        return String(value === undefined || value === null ? '' : value).replace(
            /[&<>"']/g,
            (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]),
        );
    }

    function rgbFloat(color) {
        return [color[0] / 255, color[1] / 255, color[2] / 255];
    }

    /** cos^n exponent for a given half-power beamwidth (same in theta and phi). */
    function patternExponent(hpbwDeg) {
        const half = toRadians((hpbwDeg || HPBW_DEG) / 2);
        const cosHalf = Math.cos(half);
        if (cosHalf <= 0) return 2;
        return Math.log(0.5) / Math.log(cosHalf);
    }

    /**
     * Parametric 3D lobe along +Z: r(theta,phi) = R * cos(theta)^n.
     * Surface stops at a low-gain contour (not the origin) so the wireframe
     * does not grow a solid cone of spokes back into the antenna.
     */
    function buildLobeGeometry(THREE, length, hpbwDeg) {
        const n = patternExponent(hpbwDeg);
        const thetaSteps = 16;
        const phiSteps = 28;
        const minGain = 0.08;
        const thetaMax = Math.min(Math.PI / 2 - 0.02, Math.acos(Math.pow(minGain, 1 / Math.max(n, 1e-6))));
        const positions = [];
        const indices = [];

        // Boresight tip — single vertex, not a fan collapsed at the mast.
        positions.push(0, 0, length);

        for (let ti = 1; ti <= thetaSteps; ti += 1) {
            const theta = (ti / thetaSteps) * thetaMax;
            const gain = Math.pow(Math.max(0, Math.cos(theta)), n);
            const r = length * gain;
            for (let pi = 0; pi < phiSteps; pi += 1) {
                const phi = (pi / phiSteps) * Math.PI * 2;
                positions.push(
                    r * Math.sin(theta) * Math.cos(phi),
                    r * Math.sin(theta) * Math.sin(phi),
                    r * Math.cos(theta),
                );
            }
        }

        for (let pi = 0; pi < phiSteps; pi += 1) {
            indices.push(0, 1 + pi, 1 + ((pi + 1) % phiSteps));
        }
        for (let ti = 1; ti < thetaSteps; ti += 1) {
            const ring = 1 + (ti - 1) * phiSteps;
            const next = 1 + ti * phiSteps;
            for (let pi = 0; pi < phiSteps; pi += 1) {
                const a = ring + pi;
                const b = ring + ((pi + 1) % phiSteps);
                const c = next + pi;
                const d = next + ((pi + 1) % phiSteps);
                indices.push(a, c, b);
                indices.push(b, c, d);
            }
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();
        return geometry;
    }

    function create(canvas, options) {
        const opts = options || {};
        const THREE = global.THREE;
        if (!THREE) {
            throw new Error('three.js is required for the RET hologram (load vendor/three.min.js first)');
        }

        const wrapper = canvas.parentElement;
        const state = {
            site: {},
            sectors: [],
            selected: null,
            hovered: null,
            yaw: 0,
            pitch: DEFAULT_PITCH_DEG,
            zoom: 1,
            width: 0,
            height: 0,
            frame: null,
            animating: false,
            phase: 0,
            drag: null,
            lobeMeshes: [],
            ghostMeshes: [],
            lobeRoots: [],
            patternDetail: false,
        };

        const tooltip = document.createElement('div');
        tooltip.className = 'holo-tooltip';
        tooltip.hidden = true;
        if (wrapper) wrapper.appendChild(tooltip);

        const renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: true,
            powerPreference: 'low-power',
        });
        renderer.setClearColor(0x000000, 0);
        renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1, 2));

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(42, 1, 0.5, 4000);
        const root = new THREE.Group();
        scene.add(root);

        const ambient = new THREE.AmbientLight(0xffffff, 0.7);
        const key = new THREE.DirectionalLight(0xffffff, 0.55);
        key.position.set(60, 120, 45);
        scene.add(ambient, key);

        const ground = new THREE.Mesh(
            new THREE.CircleGeometry(180, 64),
            new THREE.MeshBasicMaterial({
                color: 0x1a2433,
                transparent: true,
                opacity: 0.45,
                depthWrite: false,
            }),
        );
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.05;
        root.add(ground);

        const ringMat = new THREE.LineBasicMaterial({ color: 0x4a627a, transparent: true, opacity: 0.55 });
        [60, 105, 150].forEach((radius) => {
            const pts = [];
            for (let i = 0; i <= 64; i += 1) {
                const a = (i / 64) * Math.PI * 2;
                pts.push(new THREE.Vector3(Math.cos(a) * radius, 0.02, Math.sin(a) * radius));
            }
            root.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMat));
        });

        function makeCompassLabel(text, colorHex) {
            const c = document.createElement('canvas');
            c.width = 128;
            c.height = 128;
            const ctx = c.getContext('2d');
            ctx.clearRect(0, 0, 128, 128);
            ctx.font = 'bold 72px Segoe UI, Arial, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = colorHex;
            ctx.fillText(text, 64, 64);
            const tex = new THREE.CanvasTexture(c);
            tex.needsUpdate = true;
            const mat = new THREE.SpriteMaterial({
                map: tex,
                transparent: true,
                depthTest: false,
                depthWrite: false,
            });
            const sprite = new THREE.Sprite(mat);
            sprite.scale.set(18, 18, 1);
            return sprite;
        }

        // Cardinal axes — +Z is South in world (lookAt convention); North is −Z.
        const compassRadius = 165;
        const compassGroup = new THREE.Group();
        const axisMatN = new THREE.LineBasicMaterial({ color: 0x7eb6ff, transparent: true, opacity: 0.85 });
        const axisMat = new THREE.LineBasicMaterial({ color: 0x5a7a94, transparent: true, opacity: 0.55 });
        [
            { label: 'N', x: 0, z: -compassRadius, color: '#7eb6ff', mat: axisMatN },
            { label: 'S', x: 0, z: compassRadius, color: '#9bb4c8', mat: axisMat },
            { label: 'E', x: compassRadius, z: 0, color: '#9bb4c8', mat: axisMat },
            { label: 'W', x: -compassRadius, z: 0, color: '#9bb4c8', mat: axisMat },
        ].forEach((card) => {
            const line = new THREE.Line(
                new THREE.BufferGeometry().setFromPoints([
                    new THREE.Vector3(0, 0.08, 0),
                    new THREE.Vector3(card.x, 0.08, card.z),
                ]),
                card.mat,
            );
            compassGroup.add(line);
            const marker = new THREE.Mesh(
                new THREE.BoxGeometry(card.label === 'N' || card.label === 'S' ? 3.5 : 2.2, 1.2, card.label === 'E' || card.label === 'W' ? 3.5 : 2.2),
                new THREE.MeshBasicMaterial({ color: card.label === 'N' ? 0x7eb6ff : 0x5a7a94 }),
            );
            marker.position.set(card.x * 0.92, 0.7, card.z * 0.92);
            compassGroup.add(marker);
            const sprite = makeCompassLabel(card.label, card.color);
            sprite.position.set(card.x, 14, card.z);
            compassGroup.add(sprite);
        });
        root.add(compassGroup);

        // —— Self-supporting lattice tower (portal_tower language, three.js) ——
        const towerGroup = new THREE.Group();
        root.add(towerGroup);

        const steelMat = new THREE.LineBasicMaterial({
            color: 0x9eb4c8,
            transparent: true,
            opacity: 0.92,
        });
        const steelDimMat = new THREE.LineBasicMaterial({
            color: 0x6a8298,
            transparent: true,
            opacity: 0.55,
        });
        const steelBraceMat = new THREE.LineBasicMaterial({
            color: 0x7a94aa,
            transparent: true,
            opacity: 0.4,
        });

        function addLine(group, ax, ay, az, bx, by, bz, mat) {
            const geom = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(ax, ay, az),
                new THREE.Vector3(bx, by, bz),
            ]);
            group.add(new THREE.Line(geom, mat));
        }

        const LEG_SX = [1, 1, -1, -1];
        const LEG_SZ = [1, -1, -1, 1];
        function legPoint(leg, y) {
            const w = latticeHalfW(y);
            return { x: w * LEG_SX[leg], y, z: w * LEG_SZ[leg] };
        }

        const latticeLines = new THREE.Group();
        const segH = LATTICE_H / LATTICE_SEGMENTS;
        for (let leg = 0; leg < 4; leg += 1) {
            for (let i = 0; i < LATTICE_SEGMENTS; i += 1) {
                const y0 = i * segH;
                const y1 = y0 + segH;
                const a = legPoint(leg, y0);
                const b = legPoint(leg, y1);
                addLine(latticeLines, a.x, a.y, a.z, b.x, b.y, b.z, steelMat);
            }
        }
        for (let i = 0; i <= LATTICE_SEGMENTS; i += 1) {
            const y0 = i * segH;
            for (let leg = 0; leg < 4; leg += 1) {
                const nleg = (leg + 1) % 4;
                const a = legPoint(leg, y0);
                const c = legPoint(nleg, y0);
                addLine(latticeLines, a.x, a.y, a.z, c.x, c.y, c.z, steelDimMat);
                if (i < LATTICE_SEGMENTS) {
                    const y1 = y0 + segH;
                    const b = legPoint(leg, y1);
                    const d = legPoint(nleg, y1);
                    addLine(latticeLines, a.x, a.y, a.z, d.x, d.y, d.z, steelBraceMat);
                    addLine(latticeLines, c.x, c.y, c.z, b.x, b.y, b.z, steelBraceMat);
                }
            }
        }
        towerGroup.add(latticeLines);

        // Top work platform (octagon ring + posts) near antenna level.
        const platformY = LATTICE_H - 1.5;
        const platformR = latticeHalfW(platformY) + 3.2;
        const platPts = [];
        for (let i = 0; i <= 8; i += 1) {
            const az = Math.PI / 8 + (i / 8) * Math.PI * 2;
            platPts.push(new THREE.Vector3(
                Math.cos(az) * platformR,
                platformY,
                Math.sin(az) * platformR,
            ));
        }
        towerGroup.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(platPts),
            steelMat,
        ));
        const railPts = platPts.map((p) => new THREE.Vector3(p.x, platformY + 2.2, p.z));
        towerGroup.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(railPts),
            steelDimMat,
        ));
        for (let i = 0; i < 8; i += 1) {
            addLine(
                towerGroup,
                platPts[i].x, platformY, platPts[i].z,
                railPts[i].x, platformY + 2.2, railPts[i].z,
                steelBraceMat,
            );
        }
        for (let leg = 0; leg < 4; leg += 1) {
            const lp = legPoint(leg, platformY - 3);
            const az = Math.atan2(LEG_SZ[leg], LEG_SX[leg]);
            addLine(
                towerGroup,
                lp.x, lp.y, lp.z,
                Math.cos(az) * platformR, platformY, Math.sin(az) * platformR,
                steelDimMat,
            );
        }

        // Pipe mast above the lattice (antenna mount).
        const pipe = new THREE.Mesh(
            new THREE.CylinderGeometry(0.55, 0.85, MAST_PIPE_TOP - LATTICE_H, 10),
            new THREE.MeshStandardMaterial({
                color: 0xb8c6d4,
                metalness: 0.55,
                roughness: 0.35,
            }),
        );
        pipe.position.y = (LATTICE_H + MAST_PIPE_TOP) / 2;
        towerGroup.add(pipe);

        // Aviation beacon.
        const beacon = new THREE.Mesh(
            new THREE.SphereGeometry(0.85, 12, 10),
            new THREE.MeshStandardMaterial({
                color: 0xff4455,
                emissive: 0xaa2233,
                emissiveIntensity: 0.7,
                metalness: 0.2,
                roughness: 0.4,
            }),
        );
        beacon.position.y = BEACON_Y;
        towerGroup.add(beacon);

        // Ground equipment shelter (portal-style cabin beside the base).
        const shelterMat = new THREE.MeshStandardMaterial({
            color: 0x5c6b7c,
            metalness: 0.25,
            roughness: 0.7,
        });
        const shelter = new THREE.Mesh(new THREE.BoxGeometry(14, 7, 10), shelterMat);
        shelter.position.set(22, 3.5, 14);
        towerGroup.add(shelter);
        const shelterRoof = new THREE.Mesh(
            new THREE.BoxGeometry(15.5, 0.8, 11.5),
            new THREE.MeshStandardMaterial({ color: 0x3d4a58, metalness: 0.15, roughness: 0.8 }),
        );
        shelterRoof.position.set(22, 7.3, 14);
        towerGroup.add(shelterRoof);
        // Cable run shelter → tower base.
        addLine(towerGroup, 15, 0.5, 14, latticeHalfW(0) * 0.75, 0.5, latticeHalfW(0) * 0.75, steelDimMat);

        // One rectangular antenna panel per sector, rebuilt from inventory azimuths.
        const panelMat = new THREE.MeshStandardMaterial({
            color: 0xd7e0ea,
            metalness: 0.3,
            roughness: 0.35,
        });
        const antennaGroup = new THREE.Group();
        root.add(antennaGroup);
        state.antennaFacings = [];

        const lobeGroup = new THREE.Group();
        root.add(lobeGroup);

        const raycaster = new THREE.Raycaster();
        // LineSegments need a threshold for picking.
        raycaster.params.Line = { threshold: 2.5 };
        const pointer = new THREE.Vector2();

        function cameraDistance() {
            return CAMERA_BASE_DIST / state.zoom;
        }

        function placeCamera() {
            const dist = cameraDistance();
            const polar = toRadians(clamp(state.pitch, 0, 80));
            const yaw = toRadians(state.yaw);
            camera.position.set(
                Math.sin(polar) * Math.sin(yaw) * dist,
                Math.cos(polar) * dist,
                Math.sin(polar) * Math.cos(yaw) * dist,
            );
            camera.lookAt(0, PANEL_CENTER_Y * 0.45, 0);
            camera.updateProjectionMatrix();
        }

        function disposeObject(obj) {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
                if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
                else obj.material.dispose();
            }
        }

        function clearLobes() {
            state.lobeRoots.forEach((group) => {
                lobeGroup.remove(group);
                group.traverse(disposeObject);
            });
            state.lobeMeshes = [];
            state.ghostMeshes = [];
            state.lobeRoots = [];
        }

        function clearAntennas() {
            antennaGroup.children.slice().forEach((child) => {
                antennaGroup.remove(child);
                if (child.geometry) child.geometry.dispose();
            });
        }

        /**
         * Place one panel per sector face. Azimuth 0° = North (−Z), panel faces
         * outward along that bearing — count matches real sectors, not a fixed 3.
         */
        function rebuildAntennas() {
            clearAntennas();
            (state.antennaFacings || []).forEach((face) => {
                if (!Number.isFinite(face.azimuth)) return;
                const az = toRadians(face.azimuth);
                const panel = new THREE.Mesh(
                    new THREE.BoxGeometry(PANEL_WIDTH, PANEL_HEIGHT, PANEL_DEPTH),
                    panelMat,
                );
                const px = Math.sin(az) * PANEL_MOUNT_RADIUS;
                const pz = -Math.cos(az) * PANEL_MOUNT_RADIUS;
                panel.position.set(px, PANEL_CENTER_Y, pz);
                panel.rotation.y = -az;
                panel.userData = { sectorKey: face.key || '', label: face.label || '' };
                antennaGroup.add(panel);

                // Standoff struts from pipe mast to panel (portal_tower style).
                const strutMat = steelDimMat;
                const geomLo = new THREE.BufferGeometry().setFromPoints([
                    new THREE.Vector3(0, PANEL_CENTER_Y - PANEL_HEIGHT * 0.35, 0),
                    new THREE.Vector3(px * 0.95, PANEL_CENTER_Y - PANEL_HEIGHT * 0.3, pz * 0.95),
                ]);
                const geomHi = new THREE.BufferGeometry().setFromPoints([
                    new THREE.Vector3(0, PANEL_CENTER_Y + PANEL_HEIGHT * 0.35, 0),
                    new THREE.Vector3(px * 0.95, PANEL_CENTER_Y + PANEL_HEIGHT * 0.3, pz * 0.95),
                ]);
                antennaGroup.add(new THREE.Line(geomLo, strutMat));
                antennaGroup.add(new THREE.Line(geomHi, strutMat));
            });
        }

        /** Sector-centre azimuth for the physical panel (undo AAU half-beam offset). */
        function facingAzimuthDeg(sector) {
            const key = sector.sectorKey || String(sector.key || '').split('::')[0];
            const face = (state.antennaFacings || []).find((f) => f.key === key);
            if (face && Number.isFinite(face.azimuth)) return face.azimuth;
            let az = Number(sector.azimuth) || 0;
            const tech = primaryTech(sector);
            if (tech === '4G-AAU-Left') az = (az + 15 + 360) % 360;
            else if (tech === '4G-AAU-Right') az = (az - 15 + 360) % 360;
            return ((az % 360) + 360) % 360;
        }

        function orientLobe(obj, sector, tiltDeg, techIndex, azimuthOverride) {
            // Beam direction uses lobe azimuth (AAU Left/Right already offset).
            // Origin sits on the panel's outward face midpoint (sector facing).
            const beamAzDeg = Number.isFinite(azimuthOverride) ? azimuthOverride : Number(sector.azimuth) || 0;
            const beamAz = toRadians(beamAzDeg);
            const faceAz = toRadians(facingAzimuthDeg(sector));
            const downtilt = Number.isFinite(tiltDeg) ? Math.abs(tiltDeg) : DEFAULT_TILT_DEG;
            const elev = toRadians(-downtilt);
            const dir = new THREE.Vector3(
                Math.sin(beamAz) * Math.cos(elev),
                Math.sin(elev),
                -Math.cos(beamAz) * Math.cos(elev),
            ).normalize();
            obj.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir);
            // Slight vertical stack when several techs share one panel face.
            const lift = PANEL_CENTER_Y + (Number(techIndex) || 0) * 1.1;
            obj.position.set(
                Math.sin(faceAz) * PANEL_FACE_RADIUS,
                lift,
                -Math.cos(faceAz) * PANEL_FACE_RADIUS,
            );
        }

        function makeWireEnvelope(length, hpbw, colorRgb, opacity, userData) {
            const geometry = buildLobeGeometry(THREE, length, hpbw);
            const wireGeom = new THREE.WireframeGeometry(geometry);
            geometry.dispose();
            const wire = new THREE.LineSegments(
                wireGeom,
                new THREE.LineBasicMaterial({
                    color: new THREE.Color(colorRgb[0], colorRgb[1], colorRgb[2]),
                    transparent: true,
                    opacity,
                    depthWrite: false,
                }),
            );
            wire.userData = userData;
            return wire;
        }

        function addOrientedEnvelope(parent, sector, azimuthDeg, tiltDeg, techIndex, length, hpbw, colorRgb, opacity, userData) {
            const sub = new THREE.Group();
            sub.userData = userData;
            sub.add(makeWireEnvelope(length, hpbw, colorRgb, opacity, userData));
            orientLobe(sub, sector, tiltDeg, techIndex, azimuthDeg);
            parent.add(sub);
            return sub;
        }

        function makeLobeMesh(sector, ghost) {
            const color = sector.edited && !ghost ? EDIT_COLOR : techColor(sector.technologies);
            const [r, g, b] = rgbFloat(color);
            const tech = primaryTech(sector);
            const retTilt = ghost ? sector.baselineTiltDeg : sector.tiltDeg;
            const effTilt = effectiveTiltDeg(retTilt, sector.mechanicalTilt);
            const height = sector.height || state.site.antenna_height;
            const length = lobeLength(height, effTilt, tech);
            const hpbw = Number.isFinite(sector.beamwidth) ? sector.beamwidth : HPBW_DEG;
            const sectorKey = sector.sectorKey || String(sector.key || '').split('::')[0];
            const selected = state.selected && state.selected === sectorKey;
            const dimmed = Boolean(state.selected && !selected);
            const mainOpacity = ghost ? 0.2 : (dimmed ? 0.28 : 0.92);
            const baseAz = Number(sector.azimuth) || 0;

            const group = new THREE.Group();
            const userData = {
                key: sector.key,
                sectorKey,
                sector,
                ghost: Boolean(ghost),
            };
            group.userData = userData;

            // Main beam
            addOrientedEnvelope(
                group, sector, baseAz, effTilt, sector.techIndex,
                length, hpbw, [r, g, b], mainOpacity, userData,
            );

            // Analytical pattern: back lobe + two side lobes (reference size ratios).
            if (state.patternDetail && !ghost) {
                const backRgb = [
                    clamp(r * 0.65 + 0.2, 0, 1),
                    clamp(g * 0.65 + 0.2, 0, 1),
                    clamp(b * 0.65 + 0.22, 0, 1),
                ];
                // Side lobes tint cooler (blue) like the reference plot.
                const sideRgb = [
                    clamp(r * 0.35 + 0.12, 0, 1),
                    clamp(g * 0.55 + 0.28, 0, 1),
                    clamp(b * 0.35 + 0.72, 0, 1),
                ];
                const backOpacity = dimmed ? 0.22 : 0.78;
                const sideOpacity = dimmed ? 0.2 : 0.88;
                const backHpbw = Math.min(90, hpbw * 1.15);  // slightly fatter back
                const sideHpbw = Math.max(22, hpbw * 0.55);  // narrower petals

                addOrientedEnvelope(
                    group, sector, baseAz + BACK_LOBE_AZ_OFFSET, effTilt, sector.techIndex,
                    length * BACK_LOBE_REL_LENGTH, backHpbw, backRgb, backOpacity, userData,
                );
                [-1, 1].forEach((sign) => {
                    addOrientedEnvelope(
                        group, sector, baseAz + sign * SIDE_LOBE_AZ_OFFSET, effTilt, sector.techIndex,
                        length * SIDE_LOBE_REL_LENGTH, sideHpbw, sideRgb, sideOpacity, userData,
                    );
                });
            }

            return group;
        }

        function rebuildLobes() {
            clearLobes();
            (state.sectors || []).forEach((sector) => {
                if (!Number.isFinite(sector.azimuth)) return;
                const live = makeLobeMesh(sector, false);
                lobeGroup.add(live);
                state.lobeRoots.push(live);
                state.lobeMeshes.push(live);
                live.traverse((child) => {
                    if (child.isMesh || child.isLineSegments || child.isLine) {
                        state.lobeMeshes.push(child);
                    }
                });
                if (
                    sector.edited
                    && Number.isFinite(sector.baselineTiltDeg)
                    && sector.baselineTiltDeg !== sector.tiltDeg
                ) {
                    const ghost = makeLobeMesh(sector, true);
                    lobeGroup.add(ghost);
                    state.lobeRoots.push(ghost);
                    state.ghostMeshes.push(ghost);
                    ghost.traverse((child) => {
                        if (child.isMesh || child.isLineSegments || child.isLine) {
                            state.ghostMeshes.push(child);
                        }
                    });
                }
            });
        }

        function showTooltip(sector, clientX, clientY) {
            if (!sector) {
                tooltip.hidden = true;
                return;
            }
            const eff = effectiveTiltDeg(sector.tiltDeg, sector.mechanicalTilt);
            const reach = groundDistance(sector.height || state.site.antenna_height, eff);
            const tiltPart = Number.isFinite(sector.tiltDeg) ? formatDegrees(sector.tiltDeg) : '—';
            const mechPart = Number.isFinite(sector.mechanicalTilt)
                ? formatDegrees(sector.mechanicalTilt)
                : '—';
            const azSrc = sector.azimuthSource && sector.azimuthSource !== 'metadata'
                ? ` (${escapeHtml(sector.azimuthSource)})`
                : '';
            const tech = sector.technology || (sector.technologies && sector.technologies[0]) || '';
            const bandPct = Math.round(bandCoverageFactor(tech) * 100);
            tooltip.innerHTML = [
                `<strong>${escapeHtml(sector.label || sector.key)}</strong>`,
                tech ? `Technology ${escapeHtml(tech)} · band reach ${bandPct}%` : '',
                `Azimuth ${formatDegrees(sector.azimuth)}${azSrc}`,
                `RET ${tiltPart} + mech ${mechPart} ×${MECH_TILT_WEIGHT} → effective ${formatDegrees(eff)}`,
                `HPBW ${formatDegrees(sector.beamwidth || HPBW_DEG)}`
                    + (state.patternDetail
                        ? ' · pattern: main + 2 sides (±90°) + back (180°)'
                        : ''),
                `Ground reach ~${formatDistance(reach)}`,
            ].filter(Boolean).join('<br>');
            tooltip.hidden = false;
            const rect = (wrapper || canvas).getBoundingClientRect();
            tooltip.style.left = `${clamp(clientX - rect.left + 12, 8, rect.width - 180)}px`;
            tooltip.style.top = `${clamp(clientY - rect.top + 12, 8, rect.height - 80)}px`;
        }

        function pickSector(event) {
            const rect = canvas.getBoundingClientRect();
            pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(pointer, camera);
            const hits = raycaster.intersectObjects(state.lobeMeshes, false);
            if (!hits.length) return null;
            return hits[0].object.userData.sector || null;
        }

        function draw() {
            placeCamera();
            renderer.render(scene, camera);
        }

        function schedule() {
            if (state.frame) return;
            state.animating = true;
            const tick = () => {
                state.phase += 0.016;
                state.frame = null;
                state.lobeRoots.forEach((group) => {
                    if (group.userData.ghost) return;
                    const sectorKey = group.userData.sectorKey;
                    const selected = state.selected && state.selected === sectorKey;
                    const dimmed = Boolean(state.selected && !selected);
                    // Pulse main envelope only (first child); side lobes stay steady.
                    const mainGroup = group.children[0];
                    if (!mainGroup) return;
                    mainGroup.traverse((child) => {
                        if (!child.material || !child.isLineSegments) return;
                        const base = dimmed ? 0.28 : 0.92;
                        child.material.opacity = selected
                            ? base + 0.06 * Math.sin(state.phase * 2.2)
                            : base;
                    });
                });
                draw();
                if (state.animating) {
                    state.frame = global.requestAnimationFrame(tick);
                }
            };
            state.frame = global.requestAnimationFrame(tick);
        }

        function resize() {
            const rect = (wrapper || canvas).getBoundingClientRect();
            state.width = Math.max(320, Math.floor(rect.width) || canvas.clientWidth || 640);
            state.height = Math.max(280, Math.floor(rect.height) || canvas.clientHeight || 420);
            renderer.setSize(state.width, state.height, false);
            camera.aspect = state.width / state.height;
            camera.updateProjectionMatrix();
            draw();
        }

        function onPointerMove(event) {
            if (state.drag) {
                const dx = event.clientX - state.drag.x;
                const dy = event.clientY - state.drag.y;
                state.yaw = state.drag.yaw - dx * 0.35;
                state.pitch = clamp(state.drag.pitch + dy * 0.25, 5, 80);
                state.drag.x = event.clientX;
                state.drag.y = event.clientY;
                state.drag.yaw = state.yaw;
                state.drag.pitch = state.pitch;
                draw();
                return;
            }
            const sector = pickSector(event);
            state.hovered = sector ? (sector.sectorKey || sector.key) : null;
            canvas.style.cursor = sector ? 'pointer' : 'grab';
            showTooltip(sector, event.clientX, event.clientY);
        }

        function onPointerDown(event) {
            state.drag = {
                x: event.clientX,
                y: event.clientY,
                yaw: state.yaw,
                pitch: state.pitch,
                moved: false,
            };
            canvas.setPointerCapture(event.pointerId);
        }

        function onPointerUp(event) {
            const wasDrag = state.drag;
            state.drag = null;
            if (!wasDrag) return;
            const moved = Math.hypot(event.clientX - wasDrag.x, event.clientY - wasDrag.y) > 4
                || Math.abs(state.yaw - wasDrag.yaw) > 0.5;
            if (moved) return;
            const sector = pickSector(event);
            const sectorKey = sector ? (sector.sectorKey || String(sector.key || '').split('::')[0]) : null;
            const next = sectorKey && state.selected !== sectorKey ? sectorKey : null;
            state.selected = next;
            rebuildLobes();
            schedule();
            if (typeof opts.onSelectSector === 'function') opts.onSelectSector(next);
        }

        function onPointerLeave() {
            state.hovered = null;
            tooltip.hidden = true;
            canvas.style.cursor = 'grab';
        }

        function onWheel(event) {
            event.preventDefault();
            const factor = event.deltaY > 0 ? 0.92 : 1.08;
            state.zoom = clamp(state.zoom * factor, 0.55, 2.4);
            draw();
        }

        function onKeyDown(event) {
            const sectorKeys = [];
            (state.sectors || []).forEach((s) => {
                if (!Number.isFinite(s.azimuth)) return;
                const key = s.sectorKey || String(s.key || '').split('::')[0];
                if (key && !sectorKeys.includes(key)) sectorKeys.push(key);
            });
            if (!sectorKeys.length) return;
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            let idx = sectorKeys.indexOf(state.selected);
            if (idx < 0) idx = 0;
            else idx = event.key === 'ArrowRight'
                ? (idx + 1) % sectorKeys.length
                : (idx - 1 + sectorKeys.length) % sectorKeys.length;
            state.selected = sectorKeys[idx];
            rebuildLobes();
            schedule();
            if (typeof opts.onSelectSector === 'function') opts.onSelectSector(state.selected);
        }

        canvas.addEventListener('pointermove', onPointerMove);
        canvas.addEventListener('pointerdown', onPointerDown);
        canvas.addEventListener('pointerup', onPointerUp);
        canvas.addEventListener('pointerleave', onPointerLeave);
        canvas.addEventListener('wheel', onWheel, { passive: false });
        canvas.addEventListener('keydown', onKeyDown);
        canvas.tabIndex = 0;
        canvas.style.cursor = 'grab';

        let observer = null;
        if (typeof ResizeObserver !== 'undefined' && wrapper) {
            observer = new ResizeObserver(() => resize());
            observer.observe(wrapper);
        } else {
            global.addEventListener('resize', resize);
        }

        const api = {
            setSite(site) {
                state.site = site || {};
                draw();
            },
            /**
             * Inventory sector faces — one rectangular antenna per entry, aimed
             * at that sector's true azimuth. Call with site_layout.sectors.
             */
            setAntennaFacings(facings) {
                const list = Array.isArray(facings) ? facings : [];
                const byKey = new Map();
                list.forEach((face) => {
                    if (!face || !Number.isFinite(face.azimuth)) return;
                    const key = String(face.key || face.sectorKey || '').trim();
                    if (!key || byKey.has(key)) return;
                    byKey.set(key, {
                        key,
                        azimuth: ((Number(face.azimuth) % 360) + 360) % 360,
                        label: face.label || key,
                    });
                });
                state.antennaFacings = Array.from(byKey.values()).sort((a, b) => {
                    const aNum = /^\d+$/.test(a.key) ? Number(a.key) : Number.MAX_SAFE_INTEGER;
                    const bNum = /^\d+$/.test(b.key) ? Number(b.key) : Number.MAX_SAFE_INTEGER;
                    return aNum - bNum || a.key.localeCompare(b.key);
                });
                rebuildAntennas();
                draw();
            },
            setSectors(sectors) {
                state.sectors = Array.isArray(sectors) ? sectors : [];
                if (state.selected) {
                    const still = state.sectors.some(
                        (s) => (s.sectorKey || String(s.key || '').split('::')[0]) === state.selected,
                    );
                    if (!still) state.selected = null;
                }
                rebuildLobes();
                schedule();
            },
            setSelected(key) {
                state.selected = key || null;
                rebuildLobes();
                draw();
            },
            getSelected() {
                return state.selected;
            },
            setPatternDetail(enabled) {
                state.patternDetail = Boolean(enabled);
                rebuildLobes();
                schedule();
            },
            getPatternDetail() {
                return Boolean(state.patternDetail);
            },
            setPitch(pitchDeg) {
                state.pitch = clamp(Number(pitchDeg) || 0, 0, 80);
                draw();
            },
            setRotation(deg) {
                state.yaw = Number(deg) || 0;
                draw();
            },
            reset() {
                state.yaw = 0;
                state.pitch = DEFAULT_PITCH_DEG;
                state.zoom = 1;
                draw();
            },
            resize,
            destroy() {
                state.animating = false;
                if (state.frame) global.cancelAnimationFrame(state.frame);
                if (observer) observer.disconnect();
                else global.removeEventListener('resize', resize);
                canvas.removeEventListener('pointermove', onPointerMove);
                canvas.removeEventListener('pointerdown', onPointerDown);
                canvas.removeEventListener('pointerup', onPointerUp);
                canvas.removeEventListener('pointerleave', onPointerLeave);
                canvas.removeEventListener('wheel', onWheel);
                canvas.removeEventListener('keydown', onKeyDown);
                clearLobes();
                clearAntennas();
                renderer.dispose();
                tooltip.remove();
            },
        };

        resize();
        placeCamera();
        schedule();
        return api;
    }

    global.RetHologram = {
        create,
        groundDistance,
        lobeLength,
        effectiveTiltDeg,
        formatDegrees,
        formatDistance,
        TECH_COLORS,
        BAND_COVERAGE,
        HPBW_DEG,
        AAU_HPBW_DEG,
        DEFAULT_PITCH_DEG,
        MIN_GROUND_DISTANCE_M,
        MAX_GROUND_DISTANCE_M,
        MECH_TILT_WEIGHT,
    };
})(window);
