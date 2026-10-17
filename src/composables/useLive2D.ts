import { ref } from 'vue';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';
import type { PhonemeInfo } from './useWebSocket';

Live2DModel.registerTicker(PIXI.Ticker);

// 表情参数映射（从 exp3.json 分析得出）
const EXPRESSION_PARAMS: Record<string, { id: string; value: number }> = {
  // 面部
  '脸红': { id: 'Param31', value: 1.0 },
  '脸黑': { id: 'Param32', value: 1.0 },
  '生气': { id: 'Param33', value: 1.0 },
  '疑惑': { id: 'Param34', value: 1.0 },
  '金钱眼': { id: 'Param35', value: 1.0 },
  '爱心眼': { id: 'Param37', value: 1.0 },
  '星星眼': { id: 'Param36', value: 1.0 },
  '流泪': { id: 'Param44', value: 1.0 },
  '惊讶': { id: 'Param50', value: 1.0 },
  '白眼': { id: 'Param42', value: 1.0 },
  // 嘴巴
  '歪嘴右': { id: 'Param38', value: 1.0 },
  '歪嘴左': { id: 'Param39', value: 1.0 },
  '舌头': { id: 'Param52', value: 1.0 },
  // 发型
  '披发': { id: 'Param51', value: 2.0 },
  '马尾': { id: 'Param51', value: 1.0 },
  // 饰品
  '猫耳': { id: 'Param53', value: 1.0 },
  '王冠': { id: 'Param40', value: 1.0 },
  '翅膀': { id: 'Param41', value: 1.0 },
  '手柄': { id: 'ShouBing', value: 1.0 },
  '直播套装': { id: 'JiaJu', value: 1.0 },
};

export function useLive2D() {
  const app = ref<PIXI.Application | null>(null);
  const model = ref<Live2DModel | null>(null);

  // 分类记录当前激活的表情ID
  const currentFacial = ref('');
  const currentEyes = ref('');
  const currentMouth = ref('');
  const currentHair = ref('');
  const currentAccessories = ref<Set<string>>(new Set());
  const mouseFollowEnabled = ref(true);

  // 口型动画状态
  let mouthAnimationId: number | null = null;
  let isSpeaking = false;

  // Phoneme 时间轴数据
  let phonemeTimeline: PhonemeInfo[] = [];
  let phonemeStartTime = 0;  // 音频开始播放的时间戳
  let currentPhonemeIndex = 0;

  async function init(container: HTMLElement) {
    app.value = new PIXI.Application({
      width: container.clientWidth || 800,
      height: container.clientHeight || 600,
      backgroundColor: 0x2b2b3e,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
      autoStart: false,
    });

    const canvas = app.value.view as HTMLCanvasElement;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    container.appendChild(canvas);

    model.value = await Live2DModel.from('/models/IceGirl/IceGirl.model3.json', {
      autoUpdate: true,
      autoInteract: true,
    });

    const m = model.value as any;
    m.anchor.set(0.5, 0.5);
    m.x = app.value.screen.width / 2;
    m.y = app.value.screen.height / 2;
    m.scale.set(0.1);

    // 启用交互
    m.eventMode = 'static';
    m.cursor = 'pointer';

    // 计算头部在屏幕上的位置
    const getHeadPosition = () => {
      if (!model.value) return { x: 0, y: 0 };
      // 使用模型边界框估算头部位置
      const bounds = model.value.getBounds();
      return {
        x: bounds.x + bounds.width / 2,
        y: bounds.y + bounds.height * 0.25, // 头部大约在上方 25% 处
      };
    };

    // 覆盖 model.focus()，让库自带的鼠标跟踪以头部为原点
    const originalFocus = m.focus.bind(m);
    m.focus = (x: number, y: number, instant?: boolean) => {
      if (!mouseFollowEnabled.value) return;   // 🔥 关闭时跳过
      const head = getHeadPosition();
      const dx = x - head.x;
      const dy = y - head.y;
      const adjustedX = m.x + dx;
      const adjustedY = m.y + dy;
      originalFocus(adjustedX, adjustedY, instant);
    };

    // 🔥 初始状态同步
    m.autoInteract = mouseFollowEnabled.value;

    // 点击模型触发动作
    m.on('pointertap', () => {
      console.log('模型被点击');
      playMotion('Tap');
    });

    app.value.stage.addChild(m);
    app.value.start();

    // 播放待机动作
    setTimeout(() => {
      playMotion('Idle');
    }, 500);

    return { app: app.value, canvas };
  }

  function resize(container: HTMLElement) {
    if (!app.value || !model.value) return;
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w > 0 && h > 0) {
      app.value.renderer.resize(w, h);
      model.value.x = w / 2;
      model.value.y = h / 2;
      app.value.stage.hitArea = app.value.screen;
    }
  }

  // 挥手动作相关的参数ID
  const WAVE_PARAMS = ['Param58', 'Param59'];

  function playMotion(group: string, index?: number) {
    if (!model.value) {
      console.warn('模型未加载，无法播放动作:', group);
      return;
    }
    console.log('播放动作组:', group, '索引:', index);

    // 如果是Tap动作（包含挥手），先重置挥手参数避免残留
    if (group === 'Tap') {
      for (const paramId of WAVE_PARAMS) {
        setParam(paramId, 0);
      }
    }

    const motion = model.value.motion(group, index);

    // 监听动作结束，重置挥手参数
    if (group === 'Tap') {
      const resetWave = () => {
        for (const paramId of WAVE_PARAMS) {
          setParam(paramId, 0);
        }
      };
      // 动作时长7秒，在动作结束时立即重置
      setTimeout(resetWave, 7000);
      // 再保险：再多等一会再次重置
      setTimeout(resetWave, 7200);
    }
  }

  // 直接设置模型参数
  function setParam(id: string, value: number) {
    if (!model.value) return;
    const internal = model.value.internalModel as any;
    if (!internal) return;

    // 使用 pixi-live2d-display 提供的统一 API
    if (internal.setParam) {
      internal.setParam(id, value);
    } else {
      // 直接操作 coreModel
      const coreModel = internal.coreModel;
      if (!coreModel) return;
      if (coreModel.setParameterValueById) {
        coreModel.setParameterValueById(id, value, 1.0);
      } else if (coreModel.setParamFloat) {
        coreModel.setParamFloat(id, value);
      }
    }
  }

  // 设置表情（分类）
  function setExpression(category: string, id: string) {
    if (!model.value) return;

    switch (category) {
      case 'facial':
        // 清除之前的面部参数
        if (currentFacial.value) {
          const old = EXPRESSION_PARAMS[currentFacial.value];
          if (old) setParam(old.id, 0);
        }
        currentFacial.value = id;
        break;
      case 'eyes':
        if (currentEyes.value) {
          const old = EXPRESSION_PARAMS[currentEyes.value];
          if (old) setParam(old.id, 0);
        }
        currentEyes.value = id;
        break;
      case 'mouth':
        if (currentMouth.value) {
          const old = EXPRESSION_PARAMS[currentMouth.value];
          if (old) setParam(old.id, 0);
        }
        currentMouth.value = id;
        break;
      case 'hair':
        if (currentHair.value) {
          const old = EXPRESSION_PARAMS[currentHair.value];
          if (old) setParam(old.id, 0);
        }
        currentHair.value = id;
        break;
      case 'accessory':
        // 饰品是多选的
        if (currentAccessories.value.has(id)) {
          currentAccessories.value.delete(id);
          const param = EXPRESSION_PARAMS[id];
          if (param) setParam(param.id, 0);
          return;
        } else {
          currentAccessories.value.add(id);
        }
        break;
    }

    // 应用新参数
    if (id) {
      const param = EXPRESSION_PARAMS[id];
      if (param) {
        setParam(param.id, param.value);
      }
    }
  }

  function clearExpression() {
    if (!model.value) return;

    // 清除所有分类参数
    const allIds = [
      currentFacial.value,
      currentEyes.value,
      currentMouth.value,
      currentHair.value,
      ...currentAccessories.value,
    ];

    for (const id of allIds) {
      if (!id) continue;
      const param = EXPRESSION_PARAMS[id];
      if (param) setParam(param.id, 0);
    }

    currentFacial.value = '';
    currentEyes.value = '';
    currentMouth.value = '';
    currentHair.value = '';
    currentAccessories.value.clear();
  }
  // 🔥 切换鼠标跟随
  function setMouseFollow(enabled: boolean) {
    mouseFollowEnabled.value = enabled;
    const m = model.value as any;
    if (m) {
      m.autoInteract = enabled;
      if (!enabled) {
        // 关闭时把注视参数归零，避免视线卡在最后位置
        setParam('ParamAngleX', 0);
        setParam('ParamAngleY', 0);
        setParam('ParamEyeBallX', 0);
        setParam('ParamEyeBallY', 0);
      }
    }
    console.log(`[Live2D] 鼠标跟随: ${enabled ? '开启' : '关闭'}`);
  }

  // 音素到口型参数的映射表（与后端保持一致）
  const PHONEME_TO_MOUTH: Record<string, { open: number; form: number }> = {
    // 中文元音
    a: { open: 1.0, form: 0.0 },
    o: { open: 0.6, form: 0.5 },
    e: { open: 0.5, form: 0.0 },
    i: { open: 0.2, form: -0.8 },
    u: { open: 0.2, form: 1.0 },
    v: { open: 0.2, form: 0.8 },
    ai: { open: 0.8, form: -0.3 },
    ei: { open: 0.5, form: -0.5 },
    ao: { open: 0.7, form: 0.3 },
    ou: { open: 0.5, form: 0.6 },
    an: { open: 0.7, form: 0.0 },
    en: { open: 0.4, form: 0.0 },
    ang: { open: 0.8, form: 0.0 },
    eng: { open: 0.4, form: 0.0 },
    ong: { open: 0.5, form: 0.5 },
    er: { open: 0.4, form: 0.0 },
    // 英文元音
    aa: { open: 1.0, form: 0.0 },
    ae: { open: 0.9, form: -0.2 },
    ah: { open: 0.8, form: 0.0 },
    ao_e: { open: 0.7, form: 0.4 },
    eh: { open: 0.5, form: -0.3 },
    er_e: { open: 0.4, form: 0.0 },
    ih: { open: 0.3, form: -0.5 },
    iy: { open: 0.3, form: -0.7 },
    uh: { open: 0.3, form: 0.3 },
    uw: { open: 0.25, form: 0.9 },
    // 辅音
    b: { open: 0.0, form: 0.0 },
    p: { open: 0.0, form: 0.0 },
    m: { open: 0.0, form: 0.0 },
    f: { open: 0.1, form: 0.0 },
    d: { open: 0.1, form: 0.0 },
    t: { open: 0.1, form: 0.0 },
    n: { open: 0.15, form: 0.0 },
    l: { open: 0.2, form: 0.0 },
    g: { open: 0.1, form: 0.0 },
    k: { open: 0.1, form: 0.0 },
    h: { open: 0.2, form: 0.0 },
    j: { open: 0.15, form: -0.3 },
    q: { open: 0.15, form: -0.3 },
    x: { open: 0.2, form: -0.3 },
    zh: { open: 0.1, form: 0.0 },
    ch: { open: 0.1, form: 0.0 },
    sh: { open: 0.2, form: 0.0 },
    r: { open: 0.2, form: 0.0 },
    z: { open: 0.1, form: 0.0 },
    c: { open: 0.1, form: 0.0 },
    s: { open: 0.15, form: 0.0 },
    y: { open: 0.2, form: -0.5 },
    w: { open: 0.15, form: 0.6 },
    th: { open: 0.15, form: 0.0 },
    dh: { open: 0.15, form: 0.0 },
    ng: { open: 0.2, form: 0.0 },
    hh: { open: 0.2, form: 0.0 },
    jh: { open: 0.15, form: -0.2 },
    ch_e: { open: 0.1, form: 0.0 },
  };

  function getMouthShape(phoneme: string): { open: number; form: number } {
    const p = phoneme.toLowerCase().trim();
    if (PHONEME_TO_MOUTH[p]) return PHONEME_TO_MOUTH[p];
    // 去掉声调数字
    const noTone = p.replace(/\d/g, '');
    if (PHONEME_TO_MOUTH[noTone]) return PHONEME_TO_MOUTH[noTone];
    // 首字母匹配
    if (noTone) {
      const first = noTone[0];
      if (PHONEME_TO_MOUTH[first]) return PHONEME_TO_MOUTH[first];
    }
    return { open: 0.2, form: 0.0 };
  }

  // 设置 phoneme 时间轴数据（从后端接收）
  function setPhonemeTimeline(phonemes: PhonemeInfo[]) {
    phonemeTimeline = phonemes;
    currentPhonemeIndex = 0;
  }

  // 基于 phoneme 时间轴的精确口型同步
  function startSpeakingWithPhonemes(phonemes: PhonemeInfo[], audioStartTime?: number) {
    if (!model.value) return;
    // 如果正在说话，先停止之前的口型动画
    if (isSpeaking) {
      stopSpeaking();
    }
    isSpeaking = true;

    setPhonemeTimeline(phonemes);
    phonemeStartTime = audioStartTime || Date.now();

    // 如果没有 phoneme 数据，回退到旧模式
    if (phonemeTimeline.length === 0) {
      startSpeakingLegacy();
      return;
    }

    const animate = () => {
      if (!isSpeaking || !model.value) return;

      const now = Date.now();
      const elapsedSec = (now - phonemeStartTime) / 1000;

      // 找到当前应该播放的音素
      let activePhoneme: PhonemeInfo | null = null;
      let nextPhoneme: PhonemeInfo | null = null;

      for (let i = 0; i < phonemeTimeline.length; i++) {
        const p = phonemeTimeline[i];
        if (elapsedSec >= p.startTime && elapsedSec < p.endTime) {
          activePhoneme = p;
          nextPhoneme = phonemeTimeline[i + 1] || null;
          currentPhonemeIndex = i;
          break;
        }
        if (elapsedSec < p.startTime) {
          nextPhoneme = p;
          break;
        }
      }

      // 如果已经过了最后一个音素，停止
      if (!activePhoneme && elapsedSec > (phonemeTimeline[phonemeTimeline.length - 1]?.endTime || 0)) {
        stopSpeaking();
        return;
      }

      // 计算口型参数
      let targetOpen = 0;
      let targetForm = 0;

      if (activePhoneme) {
        const shape = getMouthShape(activePhoneme.phoneme);
        const phonemeDuration = activePhoneme.endTime - activePhoneme.startTime;
        const phonemeProgress = phonemeDuration > 0
          ? (elapsedSec - activePhoneme.startTime) / phonemeDuration
          : 0;

        // 在音素内部做平滑过渡：开头和结尾稍微闭合，中间最开
        // 使用正弦曲线让过渡更自然
        const envelope = Math.sin(phonemeProgress * Math.PI);
        targetOpen = shape.open * (0.3 + 0.7 * envelope);
        targetForm = shape.form;

        // 如果有下一个音素，做插值过渡
        if (nextPhoneme && phonemeProgress > 0.7) {
          const nextShape = getMouthShape(nextPhoneme.phoneme);
          const blend = (phonemeProgress - 0.7) / 0.3; // 0~1
          targetOpen = targetOpen * (1 - blend) + nextShape.open * blend;
          targetForm = targetForm * (1 - blend) + nextShape.form * blend;
        }
      } else if (nextPhoneme) {
        // 等待下一个音素，保持微开
        targetOpen = 0.1;
        targetForm = 0;
      }

      // 应用口型参数
      setParam('ParamMouthOpenY', Math.max(0, Math.min(1, targetOpen)));
      setParam('ParamMouthForm', Math.max(-1, Math.min(1, targetForm)));

      mouthAnimationId = requestAnimationFrame(animate);
    };

    mouthAnimationId = requestAnimationFrame(animate);
  }

  // 旧版口型动画（无 phoneme 数据时的回退方案）
  function startSpeaking(text?: string, durationMs?: number, speed: number = 150) {
    if (!model.value) return;
    // 如果正在说话，先停止
    if (isSpeaking) {
      stopSpeaking();
    }
    isSpeaking = true;

    startSpeakingLegacy(text, durationMs, speed);
  }

  function startSpeakingLegacy(text?: string, durationMs?: number, speed: number = 150) {
    const duration = durationMs || Math.max((text?.length || 0) * speed, 1000);
    const startTime = Date.now();

    const animate = () => {
      if (!isSpeaking || !model.value) return;
      const elapsed = Date.now() - startTime;

      if (elapsed >= duration) {
        stopSpeaking();
        return;
      }

      // 模拟口型开合：使用正弦波 + 随机扰动
      const progress = elapsed / duration;
      const baseOpen = Math.sin(progress * Math.PI * 10) * 0.5 + 0.5;
      const randomOpen = Math.random() * 0.3;
      const mouthOpen = Math.min(1, baseOpen + randomOpen);

      setParam('ParamMouthOpenY', mouthOpen);
      setParam('ParamMouthForm', 0);

      mouthAnimationId = requestAnimationFrame(animate);
    };

    mouthAnimationId = requestAnimationFrame(animate);
  }

  function stopSpeaking() {
    isSpeaking = false;
    phonemeTimeline = [];
    currentPhonemeIndex = 0;
    if (mouthAnimationId !== null) {
      cancelAnimationFrame(mouthAnimationId);
      mouthAnimationId = null;
    }
    setParam('ParamMouthOpenY', 0);
    setParam('ParamMouthForm', 0);
  }

  // AI 情绪映射到表情和动作
  const EMOTION_MAP: Record<string, { facial?: string; eyes?: string; motion?: string }> = {
    '开心': { facial: '脸红', eyes: '爱心眼', motion: 'Tap' },
    '害羞': { facial: '脸红', eyes: '爱心眼' },
    '生气': { facial: '生气', eyes: '白眼' },
    '难过': { facial: '流泪', eyes: '正常眼' },
    '惊讶': { facial: '惊讶', eyes: '星星眼', motion: 'Tap' },
    '疑惑': { facial: '疑惑', eyes: '正常眼' },
    '调皮': { facial: '脸黑', eyes: '星星眼', motion: 'Tap' },
    '困倦': { facial: '', eyes: '白眼' },
  };

  function applyEmotion(emotion: string) {
    const config = EMOTION_MAP[emotion];
    if (!config) return;

    if (config.facial) setExpression('facial', config.facial);
    if (config.eyes) setExpression('eyes', config.eyes);
    if (config.motion) playMotion(config.motion);
  }

  // AI 说话接口 - 外部调用
  // text: 说话文本, emotion: 情绪, durationMs: 音频时长（如果有音频播放）
  function speak(text?: string, emotion?: string, durationMs?: number) {
    if (emotion) applyEmotion(emotion);
    startSpeaking(text, durationMs);
  }

  // 带 phoneme 时间轴的说话接口
  function speakWithPhonemes(phonemes: PhonemeInfo[], emotion?: string, audioStartTime?: number) {
    if (emotion) applyEmotion(emotion);
    startSpeakingWithPhonemes(phonemes, audioStartTime);
  }

  function destroy() {
    stopSpeaking();
    if (app.value) {
      app.value.destroy(true, { children: true });
      app.value = null;
    }
    model.value = null;
  }

  return {
    app,
    model,
    currentFacial,
    currentEyes,
    currentMouth,
    currentHair,
    currentAccessories,
    init,
    resize,
    playMotion,
    setExpression,
    clearExpression,
    speak,
    speakWithPhonemes,
    applyEmotion,
    startSpeaking,
    stopSpeaking,
    destroy,
    setParam,
    mouseFollowEnabled, 
    setMouseFollow, 
  };
}