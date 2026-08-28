// 互斥类表情（只能同时存在一个）
export const EXPRESSIONS_FACIAL = [
  { name: '正常', id: '' },
  { name: '脸红', id: '脸红' },
  { name: '脸黑', id: '脸黑' },
  { name: '流泪', id: '流泪' },
  { name: '生气', id: '生气' },
  { name: '惊讶', id: '惊讶' },
  { name: '疑惑', id: '疑惑' },
];

export const EXPRESSIONS_EYES = [
  { name: '正常眼', id: '' },
  { name: '星星眼', id: '星星眼' },
  { name: '爱心眼', id: '爱心眼' },
  { name: '金钱眼', id: '金钱眼' },
  { name: '白眼', id: '白眼' },
];

export const EXPRESSIONS_MOUTH = [
  { name: '正常嘴', id: '' },
  { name: '歪嘴→', id: '歪嘴右' },
  { name: '←歪嘴', id: '歪嘴左' },
  { name: '舌头', id: '舌头' },
];

export const EXPRESSIONS_HAIR = [
  { name: '默认', id: '' },
  { name: '马尾', id: '马尾' },
];

// 饰品可多选
export const EXPRESSIONS_ACCESSORIES = [
  { name: '猫耳', id: '猫耳' },
  { name: '翅膀', id: '翅膀' },
  { name: '王冠', id: '王冠' },
  { name: '手柄', id: '手柄' },
  { name: '直播套装', id: '直播套装' },
];

export const MOTIONS = [
  { name: '待机', group: 'Idle' },
  { name: '挥手', group: 'Tap', index: 0 },
  { name: '媚眼', group: 'Tap', index: 1 },
];