// Customized low-power wrapper based on openwakeword-wasm-browser (MIT).
import * as ort from '/vendor/onnxruntime-web/ort.wasm.min.mjs';

export const MODEL_FILE_MAP = {
    alexa: 'alexa_v0.1.onnx',
    hey_mycroft: 'hey_mycroft_v0.1.onnx',
    hey_jarvis: 'hey_jarvis_v0.1.onnx',
    hey_rhasspy: 'hey_rhasspy_v0.1.onnx',
    timer: 'timer_v0.1.onnx',
    weather: 'weather_v0.1.onnx',
};

const AUDIO_PROCESSOR = `
class AudioProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.bufferSize = options?.processorOptions?.frameSize || 1280;
        this.targetSampleRate = options?.processorOptions?.targetSampleRate || 16000;
        this.sourceSampleRate = sampleRate || this.targetSampleRate;
        this.samplesPerInputSample = this.targetSampleRate / this.sourceSampleRate;
        this._emitAccumulator = 0;
        this._buffer = new Float32Array(this.bufferSize);
        this._pos = 0;
        this.port.postMessage({ type: 'audio-processor-ready', sourceSampleRate: this.sourceSampleRate, targetSampleRate: this.targetSampleRate });
    }
    _push(sample) {
        this._buffer[this._pos++] = sample;
        if (this._pos === this.bufferSize) {
            const completed = this._buffer;
            this._buffer = new Float32Array(this.bufferSize);
            this._pos = 0;
            this.port.postMessage(completed, [completed.buffer]);
        }
    }
    process(inputs) {
        const input = inputs[0]?.[0];
        if (input) {
            for (let i = 0; i < input.length; i++) {
                this._emitAccumulator += this.samplesPerInputSample;
                while (this._emitAccumulator >= 1) {
                    this._push(input[i]);
                    this._emitAccumulator -= 1;
                }
            }
        }
        return true;
    }
}
registerProcessor('audio-processor', AudioProcessor);
`;

const createEmitter = () => {
    const listeners = new Map();
    return {
        on(event, handler) {
            if (!listeners.has(event)) listeners.set(event, new Set());
            listeners.get(event).add(handler);
            return () => this.off(event, handler);
        },
        off(event, handler) {
            const set = listeners.get(event);
            if (set) set.delete(handler);
        },
        emit(event, payload) {
            const set = listeners.get(event);
            if (!set) return;
            for (const handler of Array.from(set)) handler(payload);
        }
    };
};

export class WakeWordEngine {
    constructor({
        keywords = ['hey_jarvis'],
        modelFiles = MODEL_FILE_MAP,
        baseAssetUrl = '/models',
        ortWasmPath,
        frameSize = 1280,
        sampleRate = 16000,
        vadHangoverFrames = 12,
        detectionThreshold = 0.5,
        cooldownMs = 2000,
        executionProviders = ['wasm'],
        embeddingWindowSize = 16,
        useVad = true,
        wasmThreads = 1,
        maxPendingFrames = 4,
        debug = false
    } = {}) {
        this.config = {
            keywords,
            modelFiles,
            baseAssetUrl,
            frameSize,
            sampleRate,
            vadHangoverFrames,
            detectionThreshold,
            cooldownMs,
            executionProviders,
            embeddingWindowSize,
            useVad,
            wasmThreads: Math.max(1, Math.min(4, Math.round(Number(wasmThreads) || 1))),
            maxPendingFrames: Math.max(1, Math.min(20, Math.round(Number(maxPendingFrames) || 4))),
            debug
        };
        this._configureOrt(ortWasmPath || '/vendor/onnxruntime-web/');
        this._emitter = createEmitter();
        this._melBuffer = [];
        this._embeddingWindowSize = embeddingWindowSize;
        this._activeKeywords = new Set(keywords);
        this._vadState = { h: null, c: null };
        this._isSpeechActive = false;
        this._vadHangover = 0;
        this._mediaStream = null;
        this._audioContext = null;
        this._workletNode = null;
        this._gainNode = null;
        this._pendingFrames = [];
        this._processing = false;
        this._processingNeedsReset = false;
        this._processedFrames = 0;
        this._droppedFrames = 0;
        this._processingTotalMs = 0;
        this._processingMaxMs = 0;
        this._lastStatsAt = 0;
        this._lastOverrunAt = 0;
        this._isDetectionCoolingDown = false;
        this._detectionPaused = false;
        this._loaded = false;
    }

    get loaded() {
        return this._loaded;
    }

    on(event, handler) {
        return this._emitter.on(event, handler);
    }

    off(event, handler) {
        this._emitter.off(event, handler);
    }

    async load() {
        if (this._loaded) return;
        const sessionOptions = { executionProviders: this.config.executionProviders };
        const resolver = (file) => `${this.config.baseAssetUrl.replace(/\/+$/, '')}/${file}`;
        this._debug('Loading core models with options', sessionOptions);

        const [melspecModel, embeddingModel, vadModel] = await Promise.all([
            ort.InferenceSession.create(resolver('melspectrogram.onnx'), sessionOptions),
            ort.InferenceSession.create(resolver('embedding_model.onnx'), sessionOptions),
            this.config.useVad ? ort.InferenceSession.create(resolver('silero_vad.onnx'), sessionOptions) : Promise.resolve(null)
        ]);
        this._melspecModel = melspecModel;
        this._embeddingModel = embeddingModel;
        this._vadModel = vadModel;

        this._keywordModels = {};
        let maxWindowSize = this.config.embeddingWindowSize;
        const keywordModels = await Promise.all(this.config.keywords.map(async (keyword) => {
            const file = this.config.modelFiles[keyword];
            if (!file) {
                throw new Error(`No model file configured for keyword "${keyword}"`);
            }
            const session = await ort.InferenceSession.create(resolver(file), sessionOptions);
            const windowSize = this._inferKeywordWindowSize(session) ?? this.config.embeddingWindowSize;
            const history = [];
            for (let i = 0; i < windowSize; i++) {
                history.push(new Float32Array(96).fill(0));
            }
            return { keyword, file, session, windowSize, history };
        }));
        for (const model of keywordModels) {
            maxWindowSize = Math.max(maxWindowSize, model.windowSize);
            this._keywordModels[model.keyword] = {
                session: model.session,
                scores: new Array(50).fill(0),
                windowSize: model.windowSize,
                history: model.history
            };
            this._debug('Loaded keyword model', { keyword: model.keyword, file: model.file, windowSize: model.windowSize });
        }
        this._embeddingWindowSize = maxWindowSize;
        this._debug('Embedding window size resolved', this._embeddingWindowSize);
        this._resetState();
        this._loaded = true;
        this._emitter.emit('ready');
    }

    async start({ deviceId, gain = 1.0, mediaStream = null } = {}) {
        if (!this._loaded) throw new Error('Call load() before start()');
        if (this._workletNode) return;

        this._detectionPaused = false;
        this._pendingFrames = [];
        this._processingNeedsReset = this._processing;
        this._processedFrames = 0;
        this._droppedFrames = 0;
        this._processingTotalMs = 0;
        this._processingMaxMs = 0;
        this._lastStatsAt = 0;
        this._lastOverrunAt = 0;
        if (!this._processing) this._resetState();
        this._mediaStream = mediaStream || await navigator.mediaDevices.getUserMedia({
            audio: deviceId ? { deviceId: { exact: deviceId } } : true
        });

        this._audioContext = new AudioContext({ sampleRate: this.config.sampleRate });
        if (this._audioContext.state === 'suspended') await this._audioContext.resume().catch(() => {});
        const source = this._audioContext.createMediaStreamSource(this._mediaStream);
        this._gainNode = this._audioContext.createGain();
        this._gainNode.gain.value = gain;

        const blob = new Blob([AUDIO_PROCESSOR], { type: 'application/javascript' });
        const workletURL = URL.createObjectURL(blob);
        try {
            await this._audioContext.audioWorklet.addModule(workletURL);
        } finally {
            URL.revokeObjectURL(workletURL);
        }
        this._workletNode = new AudioWorkletNode(this._audioContext, 'audio-processor', {
            processorOptions: {
                frameSize: this.config.frameSize,
                targetSampleRate: this.config.sampleRate
            }
        });

        this._workletNode.port.onmessage = (event) => {
            const chunk = event.data;
            if (!chunk) return;
            if (chunk?.type === 'audio-processor-ready') {
                this._emitter.emit('started', {
                    audioContextSampleRate: this._audioContext?.sampleRate || 0,
                    sourceSampleRate: chunk.sourceSampleRate,
                    targetSampleRate: chunk.targetSampleRate,
                    frameSize: this.config.frameSize,
                    wasmThreads: this.config.wasmThreads,
                    state: this._audioContext?.state || 'unknown'
                });
                return;
            }
            const audioChunk = chunk instanceof Float32Array ? chunk : Float32Array.from(chunk);
            this._emitter.emit('audio-chunk', {
                samples: audioChunk,
                sampleRate: this.config.sampleRate,
                at: Date.now()
            });
            if (!this._detectionPaused) this._enqueueFrame(audioChunk);
        };

        source.connect(this._gainNode);
        this._gainNode.connect(this._workletNode);
        this._workletNode.connect(this._audioContext.destination);
        this._debug('Microphone stream started', { deviceId: deviceId ?? 'default', gain });
    }

    async stop() {
        if (this._workletNode) {
            this._workletNode.port.onmessage = null;
            this._workletNode.disconnect();
            this._workletNode = null;
        }
        if (this._gainNode) {
            this._gainNode.disconnect();
            this._gainNode = null;
        }
        if (this._audioContext && this._audioContext.state !== 'closed') {
            await this._audioContext.close();
        }
        this._audioContext = null;
        this._pendingFrames = [];
        this._processingNeedsReset = this._processing;
        if (this._mediaStream) {
            this._mediaStream.getTracks().forEach((track) => track.stop());
            this._mediaStream = null;
        }
        this._isDetectionCoolingDown = false;
        this._debug('Engine stopped and media stream closed');
    }

    get started() {
        return Boolean(this._workletNode);
    }

    setGain(value) {
        if (this._gainNode) {
            this._gainNode.gain.value = value;
        }
    }

    async suspend() {
        if (this._audioContext?.state === 'running') {
            await this._audioContext.suspend().catch(() => {});
        }
    }

    async resume() {
        if (this._audioContext?.state === 'suspended') {
            await this._audioContext.resume().catch(() => {});
        }
    }

    setDetectionPaused(paused, { reset = false } = {}) {
        this._detectionPaused = Boolean(paused);
        if (this._detectionPaused) this._pendingFrames = [];
        if (reset) {
            if (this._processing) this._processingNeedsReset = true;
            else this._resetState();
        }
        this._debug(this._detectionPaused ? 'Detection paused' : 'Detection resumed');
    }

    _enqueueFrame(frame) {
        if (this._detectionPaused || !frame?.length) return;
        if (this._pendingFrames.length >= this.config.maxPendingFrames) {
            const removeCount = this._pendingFrames.length - this.config.maxPendingFrames + 1;
            this._pendingFrames.splice(0, removeCount);
            this._droppedFrames += removeCount;
            this._processingNeedsReset = true;
            const now = performance.now();
            if (!this._lastOverrunAt || now - this._lastOverrunAt >= 5_000) {
                this._lastOverrunAt = now;
                this._emitter.emit('overrun', {
                    droppedFrames: this._droppedFrames,
                    maxPendingFrames: this.config.maxPendingFrames,
                    at: now
                });
            }
        }
        this._pendingFrames.push(frame);
        if (!this._processing) void this._drainFrames();
    }

    async _drainFrames() {
        if (this._processing) return;
        this._processing = true;
        try {
            while (this._pendingFrames.length && !this._detectionPaused && this.started) {
                if (this._processingNeedsReset) {
                    this._processingNeedsReset = false;
                    this._resetState();
                }
                const frame = this._pendingFrames.shift();
                const startedAt = performance.now();
                try {
                    await this._processChunk(frame);
                } catch (error) {
                    this._emitter.emit('error', error);
                }
                const durationMs = performance.now() - startedAt;
                this._processedFrames += 1;
                this._processingTotalMs += durationMs;
                this._processingMaxMs = Math.max(this._processingMaxMs, durationMs);
                this._maybeEmitStats();
            }
        } finally {
            this._processing = false;
            if (this._pendingFrames.length && !this._detectionPaused && this.started) {
                queueMicrotask(() => void this._drainFrames());
            }
        }
    }

    _maybeEmitStats() {
        const now = performance.now();
        if (!this._lastStatsAt) {
            this._lastStatsAt = now;
            return;
        }
        if (now - this._lastStatsAt < 15_000) return;
        this._lastStatsAt = now;
        const averageFrameMs = this._processedFrames > 0 ? this._processingTotalMs / this._processedFrames : 0;
        const audioFrameMs = this.config.frameSize / this.config.sampleRate * 1000;
        this._emitter.emit('stats', {
            averageFrameMs,
            maxFrameMs: this._processingMaxMs,
            audioFrameMs,
            realtimeLoad: audioFrameMs > 0 ? averageFrameMs / audioFrameMs : 0,
            processedFrames: this._processedFrames,
            droppedFrames: this._droppedFrames,
            pendingFrames: this._pendingFrames.length,
            wasmThreads: this.config.wasmThreads,
            at: now
        });
    }

    async runWav(buffer) {
        if (!this._loaded) throw new Error('Call load() before runWav()');
        this._resetState();

        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const decoded = await audioContext.decodeAudioData(buffer.slice(0));
        const offline = new OfflineAudioContext(1, Math.ceil(decoded.length * this.config.sampleRate / decoded.sampleRate), this.config.sampleRate);
        const src = offline.createBufferSource();
        src.buffer = decoded;
        src.connect(offline.destination);
        src.start();
        const rendered = await offline.startRendering();
        const audioData = rendered.getChannelData(0);
        this._debug('Running offline WAV', { samples: audioData.length });

        const minRequiredSamples = this._embeddingWindowSize * this.config.frameSize;
        let padded = audioData;
        if (padded.length < minRequiredSamples) {
            const padding = new Float32Array(minRequiredSamples - padded.length);
            const newAudioData = new Float32Array(minRequiredSamples);
            newAudioData.set(padded, 0);
            newAudioData.set(padding, padded.length);
            padded = newAudioData;
        }

        let highest = 0;
        for (let i = 0; i < Math.floor(padded.length / this.config.frameSize); i++) {
            const chunk = padded.subarray(i * this.config.frameSize, (i + 1) * this.config.frameSize);
            await this._processChunk(chunk, { emitEvents: false });
            for (const key of Object.keys(this._keywordModels)) {
                const tail = this._keywordModels[key].scores.slice(-1)[0];
                if (tail > highest) highest = tail;
            }
        }
        return highest;
    }

    _resetState() {
        this._melBuffer = [];
        const vadShape = [2, 1, 64];
        if (!this._vadState.h) {
            this._vadState.h = new ort.Tensor('float32', new Float32Array(128).fill(0), vadShape);
            this._vadState.c = new ort.Tensor('float32', new Float32Array(128).fill(0), vadShape);
        } else {
            this._vadState.h.data.fill(0);
            this._vadState.c.data.fill(0);
        }
        this._isSpeechActive = false;
        this._vadHangover = 0;
        this._isDetectionCoolingDown = false;
        if (this._keywordModels) {
            for (const key of Object.keys(this._keywordModels)) {
                this._keywordModels[key].scores.fill(0);
                const history = this._keywordModels[key].history;
                if (history) {
                    for (let i = 0; i < history.length; i++) {
                        history[i].fill(0);
                    }
                }
            }
        }
        this._debug('Internal buffers reset');
    }

    async _processChunk(chunk, { emitEvents = true } = {}) {
        if (this.config.debug) {
            let peak = 0;
            let sumSquares = 0;
            for (let i = 0; i < chunk.length; i++) {
                const sample = chunk[i];
                sumSquares += sample * sample;
                const abs = Math.abs(sample);
                if (abs > peak) peak = abs;
            }
            const rms = Math.sqrt(sumSquares / chunk.length);
            this._debug('Chunk received', { rms: Number(rms.toFixed(4)), peak: Number(peak.toFixed(4)) });
        }
        if (this.config.useVad && this._vadModel) {
            const vadTriggered = await this._runVad(chunk);
            if (vadTriggered) {
                if (!this._isSpeechActive && emitEvents) this._emitter.emit('speech-start');
                this._isSpeechActive = true;
                this._vadHangover = this.config.vadHangoverFrames;
            } else if (this._isSpeechActive) {
                this._vadHangover -= 1;
                if (this._vadHangover <= 0) {
                    this._isSpeechActive = false;
                    if (emitEvents) this._emitter.emit('speech-end');
                }
            }
        }

        await this._runInference(chunk, this._isSpeechActive, emitEvents);
    }

    async _runVad(chunk) {
        if (!this._vadModel) return false;
        try {
            const tensor = new ort.Tensor('float32', chunk, [1, chunk.length]);
            const sr = new ort.Tensor('int64', [BigInt(this.config.sampleRate)], []);
            const res = await this._vadModel.run({ input: tensor, sr, h: this._vadState.h, c: this._vadState.c });
            this._vadState.h = res.hn;
            this._vadState.c = res.cn;
            const confidence = res.output.data[0];
            this._debug('VAD result', { confidence: Number(confidence.toFixed(3)) });
            return confidence > 0.5;
        } catch (err) {
            this._emitter.emit('error', err);
            return false;
        }
    }

    async _runInference(chunk, isSpeechActive, emitEvents) {
        const melspecTensor = new ort.Tensor('float32', chunk, [1, chunk.length]);
        const melspecResults = await this._melspecModel.run({ [this._melspecModel.inputNames[0]]: melspecTensor });
        const newMelData = melspecResults[this._melspecModel.outputNames[0]].data;

        for (let j = 0; j < newMelData.length; j++) {
            newMelData[j] = newMelData[j] / 10.0 + 2.0;
        }
        const melFrameCount = Math.floor(newMelData.length / 32);
        for (let j = 0; j < melFrameCount; j++) {
            this._melBuffer.push(new Float32Array(newMelData.subarray(j * 32, (j + 1) * 32)));
        }

        while (this._melBuffer.length >= 76) {
            const windowFrames = this._melBuffer.slice(0, 76);
            const flattenedMel = new Float32Array(76 * 32);
            for (let j = 0; j < windowFrames.length; j++) {
                flattenedMel.set(windowFrames[j], j * 32);
            }

            const embeddingFeeds = { [this._embeddingModel.inputNames[0]]: new ort.Tensor('float32', flattenedMel, [1, 76, 32, 1]) };
            const embeddingOut = await this._embeddingModel.run(embeddingFeeds);
            const newEmbedding = embeddingOut[this._embeddingModel.outputNames[0]].data;

            const embeddingVector = new Float32Array(newEmbedding);

            for (const name of Object.keys(this._keywordModels)) {
                const keywordModel = this._keywordModels[name];
                keywordModel.history.shift();
                keywordModel.history.push(embeddingVector);

                const flattenedEmbeddings = new Float32Array(keywordModel.windowSize * 96);
                for (let j = 0; j < keywordModel.history.length; j++) {
                    flattenedEmbeddings.set(keywordModel.history[j], j * 96);
                }
                const finalInput = new ort.Tensor('float32', flattenedEmbeddings, [1, keywordModel.windowSize, 96]);
                const results = await keywordModel.session.run({ [keywordModel.session.inputNames[0]]: finalInput });
                const score = results[keywordModel.session.outputNames[0]].data[0];
                keywordModel.scores.shift();
                keywordModel.scores.push(score);
                this._debug('Keyword score', { keyword: name, score: Number(score.toFixed(3)), windowSize: keywordModel.windowSize });

                const keywordActive = this._activeKeywords.has(name);
                if (emitEvents && keywordActive) {
                    this._emitter.emit('score', { keyword: name, score, isSpeechActive, at: performance.now() });
                }
                if (emitEvents && keywordActive && score > this.config.detectionThreshold && !this._isDetectionCoolingDown) {
                    this._isDetectionCoolingDown = true;
                    this._debug('Detection emitted', { keyword: name, score, isSpeechActive });
                    this._emitter.emit('detect', { keyword: name, score, isSpeechActive, at: performance.now() });
                    setTimeout(() => { this._isDetectionCoolingDown = false; }, this.config.cooldownMs);
                } else if (emitEvents && !keywordActive) {
                    this._debug('Detection suppressed (inactive keyword)', { keyword: name, score });
                }
            }
            this._melBuffer.splice(0, 8);
        }
    }

    _configureOrt(path) {
        if (path) ort.env.wasm.wasmPaths = path;
        // ORT otherwise uses up to four WASM workers on cross-origin-isolated
        // phones. One worker is slower per inference but substantially lowers
        // sustained CPU/package power for an always-on wake-word loop.
        ort.env.wasm.numThreads = this.config.wasmThreads;
    }

    _inferKeywordWindowSize(session) {
        if (!session) return undefined;
        const metadata = session.inputMetadata;
        const inputName = session.inputNames?.[0];
        if (!metadata || !inputName) return undefined;
        let meta;
        if (Array.isArray(metadata)) {
            meta = metadata.find((m) => m?.name === inputName) || metadata[0];
        } else {
            meta = metadata[inputName];
        }
        if (!meta || !meta.isTensor || !Array.isArray(meta.shape)) return undefined;
        const dim = meta.shape[1];
        return typeof dim === 'number' && Number.isFinite(dim) ? dim : undefined;
    }

    _debug(...args) {
        if (this.config.debug) {
            console.debug('[WakeWordEngine]', ...args);
        }
    }

    setActiveKeywords(keywords) {
        const next = Array.isArray(keywords) && keywords.length ? keywords : this.config.keywords;
        this._activeKeywords = new Set(next);
        this._debug('Active keywords updated', Array.from(this._activeKeywords));
    }
}
