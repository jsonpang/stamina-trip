/**
 * 体力预算规划师 - Fliggy 飞猪风格现代旅行单页应用
 * 2026 飞猪 AI 旅行创新大赛参赛作品
 */

(function () {
  'use strict';

  // API 与数据源配置
  const API_ENDPOINT = '/plan';
  const SAMPLE_DATA_URL = './sample-plan.json';

  // 状态管理
  const state = {
    currentData: null,
    selectedDayIndex: 0, // 0: 第1天, 1: 第2天, -1: 全部天数全览
    isLoading: false,
    timerInterval: null,
    elapsedSeconds: 0,
    isSampleData: false,
    traceExpanded: true
  };

  // DOM 元素引用
  const dom = {
    topBanner: document.getElementById('top-banner'),
    bannerBadge: document.getElementById('banner-badge'),
    bannerText: document.getElementById('banner-text'),
    bannerClose: document.getElementById('banner-close'),
    
    queryInput: document.getElementById('query-input'),
    presetChips: document.getElementById('preset-chips'),
    submitBtn: document.getElementById('submit-btn'),
    reloadSampleBtn: document.getElementById('reload-sample-btn'),
    
    progressContainer: document.getElementById('progress-container'),
    progressStatusText: document.getElementById('progress-status-text'),
    progressTimer: document.getElementById('progress-timer'),
    progressBarFill: document.getElementById('progress-bar-fill'),
    
    fallbackBanner: document.getElementById('fallback-banner'),
    
    errorBox: document.getElementById('error-message-box'),
    errorTitle: document.getElementById('error-title'),
    errorDetail: document.getElementById('error-detail'),
    
    // 画像卡
    profileMetaCity: document.getElementById('profile-meta-city'),
    profileTravelers: document.getElementById('profile-travelers'),
    profileStepCap: document.getElementById('profile-step-cap'),
    profileNoonRest: document.getElementById('profile-noon-rest'),
    profileBudget: document.getElementById('profile-budget'),
    
    // 核心对比
    daySelectorTabs: document.getElementById('day-selector-tabs'),
    comparisonColumns: document.getElementById('comparison-columns'),
    
    // 体力账单
    billDayFilter: document.getElementById('bill-day-filter'),
    staminaBillTbody: document.getElementById('stamina-bill-tbody'),
    
    // 酒店
    hotelCardContainer: document.getElementById('hotel-card-container'),
    
    // 智能体决策
    toolTraceSection: document.getElementById('tool-trace-section'),
    toolTraceToggleHeader: document.getElementById('tool-trace-toggle-header'),
    traceToggleBtn: document.getElementById('trace-toggle-btn'),
    traceToggleText: document.getElementById('trace-toggle-text'),
    toolTraceBody: document.getElementById('tool-trace-body'),
    traceStepCount: document.getElementById('trace-step-count'),
    toolTraceTimeline: document.getElementById('tool-trace-timeline'),
    agentModeBadge: document.getElementById('agent-mode-badge'),
    
    // 页脚
    claimsAuditBar: document.getElementById('claims-audit-bar'),
    claimsAuditText: document.getElementById('claims-audit-text'),
    warningsBox: document.getElementById('warnings-box'),
    warningsList: document.getElementById('warnings-list'),
    systemMessagesBox: document.getElementById('system-messages-box'),
    systemMessagesPre: document.getElementById('system-messages-pre')
  };

  /**
   * 安全处理：仅允许安全的 https:// URL，防 XSS 和协议劫持
   */
  function sanitizeHttpsUrl(url) {
    if (typeof url !== 'string') return '';
    const trimmed = url.trim();
    if (trimmed.startsWith('https://')) {
      return trimmed;
    }
    return '';
  }

  /**
   * 安全文本转义
   */
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * 数字格式化（千分位）
   */
  function formatNumber(num) {
    if (typeof num !== 'number' || isNaN(num)) return '0';
    return num.toLocaleString('zh-CN');
  }

  /**
   * 格式化米数为公里/米
   */
  function formatDistance(meters) {
    if (typeof meters !== 'number' || isNaN(meters)) return '0 m';
    if (meters >= 1000) {
      return (meters / 1000).toFixed(1) + ' km';
    }
    return Math.round(meters) + ' m';
  }

  /**
   * 显示横幅提示
   */
  function showBanner(type, message) {
    if (!dom.topBanner) return;
    dom.topBanner.classList.remove('hidden');
    if (type === 'sample') {
      dom.bannerBadge.textContent = '演示数据';
      dom.bannerBadge.style.backgroundColor = '#FFDD00';
      dom.bannerBadge.style.color = '#1A1A1A';
      dom.bannerText.textContent = message || '当前未连接到后端规划服务，已自动为您载入「演示数据」。';
    } else if (type === 'live') {
      dom.bannerBadge.textContent = '实时服务';
      dom.bannerBadge.style.backgroundColor = '#00B578';
      dom.bannerBadge.style.color = '#FFFFFF';
      dom.bannerText.textContent = message || '已成功连接飞猪 fly.ai 规划服务，当前展示最新模型实时推理行程。';
    } else {
      dom.bannerBadge.textContent = '提示';
      dom.bannerText.textContent = message;
    }
  }

  /**
   * 显示错误卡片
   */
  function showError(title, detail) {
    if (!dom.errorBox) return;
    dom.errorBox.classList.remove('hidden');
    dom.errorTitle.textContent = title;
    dom.errorDetail.textContent = detail;
  }

  /**
   * 隐藏错误卡片
   */
  function hideError() {
    if (dom.errorBox) {
      dom.errorBox.classList.add('hidden');
      dom.errorDetail.textContent = '';
    }
  }

  /**
   * 启动加载进度与计时（只显示「正在生成，通常需要 30–90 秒」+ 已等待秒数计时）
   */
  function startProgress() {
    state.isLoading = true;
    state.elapsedSeconds = 0;
    hideError();

    dom.submitBtn.disabled = true;
    const spinner = dom.submitBtn.querySelector('.btn-spinner');
    if (spinner) spinner.classList.remove('hidden');
    const btnText = dom.submitBtn.querySelector('.btn-text');
    if (btnText) btnText.textContent = '规划中...';

    dom.progressContainer.classList.remove('hidden');
    dom.progressStatusText.textContent = '正在生成，通常需要 30–90 秒';
    dom.progressTimer.textContent = '已等待 0 秒';

    if (state.timerInterval) clearInterval(state.timerInterval);

    state.timerInterval = setInterval(() => {
      state.elapsedSeconds += 1;
      dom.progressTimer.textContent = `已等待 ${state.elapsedSeconds} 秒`;
    }, 1000);
  }

  /**
   * 停止加载进度
   */
  function stopProgress() {
    state.isLoading = false;
    if (state.timerInterval) {
      clearInterval(state.timerInterval);
      state.timerInterval = null;
    }

    dom.submitBtn.disabled = false;
    const spinner = dom.submitBtn.querySelector('.btn-spinner');
    if (spinner) spinner.classList.add('hidden');
    const btnText = dom.submitBtn.querySelector('.btn-text');
    if (btnText) btnText.textContent = '生成行程规划';

    dom.progressContainer.classList.add('hidden');
  }

  /**
   * 载入演示数据 (sample-plan.json)
   */
  async function loadSampleData(isInitial) {
    try {
      const res = await fetch(SAMPLE_DATA_URL);
      if (!res.ok) {
        throw new Error(`加载离线样例文件失败 (HTTP ${res.status})`);
      }
      const data = await res.json();
      state.currentData = data;
      state.isSampleData = true;
      hideError();
      stopProgress();
      showBanner('sample', '当前展示的是一次预先生成的真实规划结果（生成时间见页脚）。输入需求后点击「生成行程规划」可实时规划。');
      if (typeof data.query === 'string') dom.queryInput.value = data.query;
      renderAll(data);
    } catch (err) {
      showError('演示数据载入失败', err.message || '请检查 sample-plan.json 是否位于同目录下。');
    }
  }

  /**
   * 初始化
   */
  async function initApp() {
    bindEvents();

    // 默认填入第一个示例需求
    const firstChip = dom.presetChips.querySelector('.chip-btn');
    if (firstChip && firstChip.dataset.preset) {
      dom.queryInput.value = firstChip.dataset.preset;
    }

    // 打开页面只展示预先生成的真实输出；每次 POST /plan 都会调用模型和飞猪，只在用户点击生成时发起。
    await loadSampleData(true);
  }

  /**
   * 用户提交需求
   */
  async function handleSubmit() {
    const query = dom.queryInput.value.trim();
    if (!query) {
      showError('输入需求为空', '请输入您的出游需求（如城市、出行天数、同行人及体力上限等）。');
      return;
    }

    startProgress();

    try {
      const res = await fetch(API_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query })
      });

      if (res.status === 200) {
        const data = await res.json();
        state.currentData = data;
        state.isSampleData = false;
        showBanner('live', '规划成功！已基于飞猪 fly.ai 实时数据生成体力预算行程。');
        renderAll(data);
      } else if (res.status === 422) {
        let detailMsg = '出行需求不完整，请提供城市、出行天数及同行人情况。';
        try {
          const errData = await res.json();
          if (errData && errData.detail) {
            detailMsg = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
          }
        } catch (_) {}
        showError('需求信息不完整 (422)', detailMsg);
      } else if (res.status === 503) {
        showError('服务暂不可用 (503)', '后端规划服务繁忙或暂不可用，请稍后重试。您可点击下方「载入演示数据」查看效果。');
      } else {
        showError('请求返回异常', `服务端响应状态码: ${res.status}`);
      }
    } catch (networkErr) {
      showError(
        '未能连接到后端接口 (503 / 连接超时)',
        `后端服务未启动或连接异常 (${networkErr.message})。您可以点击「载入演示数据」按钮，预览演示方案。`
      );
    } finally {
      stopProgress();
    }
  }

  /**
   * 绑定事件
   */
  function bindEvents() {
    dom.submitBtn.addEventListener('click', handleSubmit);

    dom.queryInput.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        handleSubmit();
      }
    });

    dom.reloadSampleBtn.addEventListener('click', () => {
      loadSampleData(false);
    });

    dom.presetChips.addEventListener('click', (e) => {
      const chip = e.target.closest('.chip-btn');
      if (!chip) return;
      
      const allChips = dom.presetChips.querySelectorAll('.chip-btn');
      allChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');

      const presetText = chip.dataset.preset;
      if (presetText) {
        dom.queryInput.value = presetText;
        dom.queryInput.focus();
      }
    });

    dom.bannerClose.addEventListener('click', () => {
      dom.topBanner.classList.add('hidden');
    });

    dom.toolTraceToggleHeader.addEventListener('click', () => {
      toggleToolTrace();
    });
  }

  /**
   * 折叠/展开决策过程
   */
  function toggleToolTrace() {
    state.traceExpanded = !state.traceExpanded;
    if (state.traceExpanded) {
      dom.toolTraceBody.classList.remove('hidden');
      dom.toolTraceToggleHeader.classList.add('expanded');
      dom.traceToggleText.textContent = '收起过程';
    } else {
      dom.toolTraceBody.classList.add('hidden');
      dom.toolTraceToggleHeader.classList.remove('expanded');
      dom.traceToggleText.textContent = '展开过程';
    }
  }

  /**
   * 全量数据渲染主入口
   */
  function renderAll(data) {
    if (!data) return;

    // 1. 渲染画像卡
    renderProfile(data.profile);

    // 2. 渲染核心对比 (普通版 vs 体力版)
    renderComparisonSection(data);

    // 3. 渲染体力账单 (体力版逐段明细)
    renderStaminaBill(data.stamina);

    // 4. 渲染酒店推荐
    renderHotelCard(data.hotel, data.hotel_stay);

    // 5. 渲染智能体决策过程 (tool_trace 及 fallback 提示)
    renderToolTrace(data);

    // 6. 渲染页脚提示与说明 (warnings, removed_claims, system_messages)
    renderFooterMeta(data);
  }

  /**
   * 1. 渲染画像卡 Profile
   */
  function renderProfile(profile) {
    if (!profile) return;

    // 城市与日期
    const city = profile.city || '未知城市';
    const dates = profile.dates && profile.dates.length ? profile.dates : [];
    const dateRangeStr = dates.length > 1 
      ? `${dates[0]} 至 ${dates[dates.length - 1]} (共 ${dates.length} 天)`
      : (dates[0] || '出行日期自选');
    dom.profileMetaCity.textContent = `${city} · ${dateRangeStr}`;

    // 同行人标签：只展示 JSON 里实际存在的 age 与 mobility
    dom.profileTravelers.innerHTML = '';
    const travelers = profile.travelers || [];
    if (travelers.length === 0) {
      const placeholder = document.createElement('span');
      placeholder.className = 'placeholder-text';
      placeholder.textContent = '未提取到同行人信息';
      dom.profileTravelers.appendChild(placeholder);
    } else {
      travelers.forEach(t => {
        const tag = document.createElement('span');
        tag.className = 'traveler-tag';
        
        const isLimited = t.mobility === 'limited';
        const isChild = t.age <= 12;

        if (isLimited) {
          tag.classList.add('limited');
        } else if (isChild) {
          tag.classList.add('child');
        }

        let mobilityStr = '';
        if (t.mobility === 'limited') {
          mobilityStr = '行动受限';
        } else if (t.mobility === 'normal') {
          mobilityStr = '行动正常';
        } else if (t.mobility) {
          mobilityStr = t.mobility;
        }

        tag.textContent = mobilityStr ? `${t.age}岁 · ${mobilityStr}` : `${t.age}岁`;
        dom.profileTravelers.appendChild(tag);
      });
    }

    // 每日步数红线
    const cap = profile.daily_step_cap;
    dom.profileStepCap.textContent = cap ? `${formatNumber(cap)} 步 / 天` : '未设置';

    // 午间休整
    dom.profileNoonRest.textContent = profile.need_noon_rest === true 
      ? '需要午休' 
      : (profile.need_noon_rest === false ? '无需午休' : '未设置');

    // 住宿预算
    dom.profileBudget.textContent = profile.budget_per_night 
      ? `¥${formatNumber(profile.budget_per_night)} / 晚` 
      : '无限制';
  }

  /**
   * 2. 渲染核心对比 (普通版 vs 体力版)
   */
  function renderComparisonSection(data) {
    const ordinaryDays = data.ordinary || [];
    const staminaDays = data.stamina || [];
    const dayCount = Math.max(ordinaryDays.length, staminaDays.length);

    // 渲染天数切换 Tabs
    dom.daySelectorTabs.innerHTML = '';
    if (dayCount > 1) {
      for (let i = 0; i < dayCount; i++) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `day-tab-btn ${state.selectedDayIndex === i ? 'active' : ''}`;
        const dayLabel = staminaDays[i]?.date ? staminaDays[i].date.substring(5) : `Day ${i + 1}`;
        btn.textContent = `第 ${i + 1} 天 (${dayLabel})`;
        btn.dataset.dayIndex = i;
        btn.addEventListener('click', () => {
          state.selectedDayIndex = i;
          renderComparisonColumns(data);
          updateDayTabActiveState();
          renderStaminaBill(data.stamina);
        });
        dom.daySelectorTabs.appendChild(btn);
      }

      // 全部天数全览 Tab
      const allBtn = document.createElement('button');
      allBtn.type = 'button';
      allBtn.className = `day-tab-btn ${state.selectedDayIndex === -1 ? 'active' : ''}`;
      allBtn.textContent = '两日对比全览';
      allBtn.dataset.dayIndex = -1;
      allBtn.addEventListener('click', () => {
        state.selectedDayIndex = -1;
        renderComparisonColumns(data);
        updateDayTabActiveState();
        renderStaminaBill(data.stamina);
      });
      dom.daySelectorTabs.appendChild(allBtn);
    }

    renderComparisonColumns(data);
  }

  function updateDayTabActiveState() {
    const btns = dom.daySelectorTabs.querySelectorAll('.day-tab-btn');
    btns.forEach(btn => {
      const idx = parseInt(btn.dataset.dayIndex, 10);
      if (idx === state.selectedDayIndex) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  /**
   * 渲染对比双栏内容
   */
  function renderComparisonColumns(data) {
    const ordinaryDays = data.ordinary || [];
    const staminaDays = data.stamina || [];
    dom.comparisonColumns.innerHTML = '';

    const targetDays = [];
    if (state.selectedDayIndex === -1) {
      for (let i = 0; i < Math.max(ordinaryDays.length, staminaDays.length); i++) {
        targetDays.push(i);
      }
    } else {
      targetDays.push(state.selectedDayIndex);
    }

    targetDays.forEach(dayIdx => {
      const ordDay = ordinaryDays[dayIdx] || null;
      const stmDay = staminaDays[dayIdx] || null;

      const dayWrap = document.createElement('div');
      dayWrap.className = 'comparison-day-block';
      dayWrap.style.width = '100%';
      dayWrap.style.display = 'flex';
      dayWrap.style.flexDirection = 'column';
      dayWrap.style.gap = '14px';
      dayWrap.style.marginBottom = targetDays.length > 1 ? '24px' : '0';

      if (targetDays.length > 1) {
        const dayTitle = document.createElement('div');
        dayTitle.style.fontWeight = '800';
        dayTitle.style.fontSize = '15px';
        dayTitle.style.color = '#1F2329';
        dayTitle.style.padding = '4px 0';
        const dateStr = stmDay?.date || ordDay?.date || '';
        dayTitle.textContent = `📅 ${dateStr}（第 ${dayIdx + 1} 天）`;
        dayWrap.appendChild(dayTitle);
      }

      const columnsRow = document.createElement('div');
      columnsRow.className = 'comparison-columns';

      // 左栏：普通版
      const ordCol = createPlanColumn(ordDay, false, dayIdx, data);
      // 右栏：体力版
      const stmCol = createPlanColumn(stmDay, true, dayIdx, data);

      columnsRow.appendChild(ordCol);
      columnsRow.appendChild(stmCol);
      dayWrap.appendChild(columnsRow);
      dom.comparisonColumns.appendChild(dayWrap);
    });
  }

  /**
   * 创建单侧方案栏 (普通版或体力版)
   */
  function createPlanColumn(dayData, isStamina, dayIdx, fullData) {
    const col = document.createElement('div');
    col.className = `plan-column ${isStamina ? 'stamina-plan' : 'ordinary-plan'}`;

    if (!dayData) {
      col.textContent = '暂无该日行程数据';
      return col;
    }

    const totalSteps = dayData.total_steps || 0;
    const cap = dayData.cap || 6000;
    const isOver = dayData.over_cap || totalSteps > cap;
    const overSteps = totalSteps - cap;
    const percent = Math.round((totalSteps / cap) * 100);

    // 1. 栏头
    const colHeader = document.createElement('div');
    colHeader.className = 'col-header';

    const titleGroup = document.createElement('div');
    titleGroup.className = 'col-title-group';

    const badge = document.createElement('span');
    badge.className = 'col-badge';
    badge.textContent = isStamina ? '体力版' : '普通版';

    const title = document.createElement('h3');
    title.className = 'col-title';
    title.textContent = isStamina ? '体力预算保护方案' : '普通版方案';

    titleGroup.appendChild(badge);
    titleGroup.appendChild(title);

    const statusPill = document.createElement('span');
    statusPill.className = `col-status-pill ${isOver ? 'status-danger' : 'status-safe'}`;
    statusPill.textContent = isOver 
      ? `超标 +${formatNumber(overSteps)} 步 (上限 ${formatNumber(cap)} 步)` 
      : `未超标 (${formatNumber(totalSteps)} / ${formatNumber(cap)} 步)`;

    colHeader.appendChild(titleGroup);
    colHeader.appendChild(statusPill);
    col.appendChild(colHeader);

    // 2. 步数进度条与对比仪表
    const meterBox = document.createElement('div');
    meterBox.className = 'step-meter-box';

    const meterTop = document.createElement('div');
    meterTop.className = 'step-meter-top';

    const currentWrap = document.createElement('div');
    currentWrap.className = 'step-current-wrap';

    const numSpan = document.createElement('span');
    numSpan.className = 'step-number';
    numSpan.textContent = formatNumber(totalSteps);

    const unitSpan = document.createElement('span');
    unitSpan.className = 'step-unit';
    unitSpan.textContent = dayData.estimated ? '步 (估算)' : '步';

    currentWrap.appendChild(numSpan);
    currentWrap.appendChild(unitSpan);

    const capInfo = document.createElement('span');
    capInfo.className = 'step-cap-info';
    capInfo.textContent = `上限: ${formatNumber(cap)} 步`;

    meterTop.appendChild(currentWrap);
    meterTop.appendChild(capInfo);
    meterBox.appendChild(meterTop);

    // 进度条轨道
    const barTrack = document.createElement('div');
    barTrack.className = 'step-bar-track';

    const barFill = document.createElement('div');
    barFill.className = `step-bar-fill ${isOver ? 'bar-over' : 'bar-safe'}`;
    const fillWidth = isOver ? 100 : Math.min(percent, 100);
    barFill.style.width = `${fillWidth}%`;
    barTrack.appendChild(barFill);
    meterBox.appendChild(barTrack);

    // 进度条底部说明
    const meterFoot = document.createElement('div');
    meterFoot.className = 'step-meter-foot';
    if (isOver) {
      meterFoot.textContent = `已超过上限 ${formatNumber(overSteps)} 步 (上限 ${formatNumber(cap)} 步)`;
    } else {
      const remaining = cap - totalSteps;
      meterFoot.textContent = `未超过上限，剩余 ${formatNumber(remaining)} 步 (上限 ${formatNumber(cap)} 步)`;
    }
    meterBox.appendChild(meterFoot);
    col.appendChild(meterBox);

    // 3. 景点游览动线
    const seqTitle = document.createElement('div');
    seqTitle.className = 'poi-sequence-title';
    seqTitle.textContent = `游览动线（共 ${dayData.pois.length} 处景点）`;
    col.appendChild(seqTitle);

    const poiList = document.createElement('div');
    poiList.className = 'poi-list';

    const pois = dayData.pois || [];
    const restCard = (restItem) => {
      const noonRestBox = document.createElement('div');
      noonRestBox.className = 'poi-noon-rest-card';
      const restTag = document.createElement('span');
      restTag.className = 'noon-rest-tag';
      restTag.textContent = restItem.mode || '午休';
      const restText = document.createElement('span');
      restText.textContent = restItem.name; // bill 里的活动名原文
      noonRestBox.appendChild(restTag);
      noonRestBox.appendChild(restText);
      return noonRestBox;
    };

    // 体力版按 bill 的实际顺序排列景点和午休；普通版没有午休，按 pois 顺序。
    let shown = 0;
    if (isStamina && Array.isArray(dayData.bill)) {
      dayData.bill.forEach(row => {
        if (row.kind === 'rest') {
          poiList.appendChild(restCard(row));
        } else if (row.kind === 'visit' && shown < pois.length) {
          poiList.appendChild(createPoiCard(pois[shown], shown + 1));
          shown += 1;
        }
      });
    }
    pois.slice(shown).forEach((poi, i) => poiList.appendChild(createPoiCard(poi, shown + i + 1)));

    col.appendChild(poiList);

    // 4. 体力规划说明：只在体力版且 explanation 字段存在时显示，只显示 explanation 原文
    if (isStamina && fullData && fullData.explanation && Array.isArray(fullData.explanation) && fullData.explanation.length > 0) {
      const currentPoiNames = new Set(pois.map(p => p.name));
      const matchingExps = fullData.explanation.filter(exp => {
        if (!exp) return false;
        if (typeof exp === 'string') return true;
        if (exp.poi) return currentPoiNames.has(exp.poi);
        return true;
      });

      if (matchingExps.length > 0) {
        const explanationBox = document.createElement('div');
        explanationBox.className = 'plan-summary-note';

        const expTitle = document.createElement('div');
        expTitle.className = 'explanation-title';
        expTitle.textContent = '体力规划说明 (explanation)：';
        explanationBox.appendChild(expTitle);

        const expList = document.createElement('ul');
        expList.className = 'explanation-list';
        matchingExps.forEach(exp => {
          const li = document.createElement('li');
          if (typeof exp === 'object' && exp !== null) {
            li.textContent = exp.poi ? `${exp.poi}：${exp.text || ''}` : (exp.text || JSON.stringify(exp));
          } else {
            li.textContent = String(exp);
          }
          expList.appendChild(li);
        });
        explanationBox.appendChild(expList);
        col.appendChild(explanationBox);
      }
    }

    return col;
  }

  /**
   * 创建景点卡片 (事实严格对应 JSON 字段)
   */
  function createPoiCard(poi, orderIdx) {
    const card = document.createElement('div');
    card.className = 'poi-item-card';

    // 缩略图
    const img = document.createElement('img');
    img.className = 'poi-thumb';
    const safePic = sanitizeHttpsUrl(poi.mainPic);
    img.src = safePic || 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="68" height="68" fill="%23eee"%3E%3Crect width="68" height="68"/%3E%3C/svg%3E';
    img.alt = poi.name || '景点图片';
    img.loading = 'lazy';
    img.onerror = function() {
      this.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="68" height="68" fill="%23f0f2f5"%3E%3Crect width="68" height="68"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="10" fill="%23999"%3E景点图%3C/text%3E%3C/svg%3E';
    };
    card.appendChild(img);

    // 信息主体
    const info = document.createElement('div');
    info.className = 'poi-info';

    // 名称与序号
    const nameRow = document.createElement('div');
    nameRow.className = 'poi-name-row';

    const titleWrap = document.createElement('div');
    titleWrap.style.display = 'flex';
    titleWrap.style.alignItems = 'center';
    titleWrap.style.minWidth = '0';

    const idxSpan = document.createElement('span');
    idxSpan.className = 'poi-order-idx';
    idxSpan.textContent = String(orderIdx);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'poi-name';
    nameSpan.textContent = poi.name || '未命名景点';

    titleWrap.appendChild(idxSpan);
    titleWrap.appendChild(nameSpan);
    nameRow.appendChild(titleWrap);
    info.appendChild(nameRow);

    // 标签与榜单 (只在字段存在时显示)
    const tagsRow = document.createElement('div');
    tagsRow.className = 'poi-tags-row';

    if (poi.category && typeof poi.category === 'string') {
      const cat = document.createElement('span');
      cat.className = 'poi-category-tag';
      cat.textContent = poi.category;
      tagsRow.appendChild(cat);
    }

    if (poi.listRank && typeof poi.listRank === 'string') {
      const rank = document.createElement('span');
      rank.className = 'poi-rank-tag';
      rank.textContent = poi.listRank;
      tagsRow.appendChild(rank);
    }
    if (tagsRow.children.length > 0) {
      info.appendChild(tagsRow);
    }

    // 价格与预订外链
    const priceRow = document.createElement('div');
    priceRow.className = 'poi-price-row';

    const priceBox = document.createElement('div');
    // 门票价格用 ticketInfo.price，没有就不显示价格（不要写「免费开放」，除非 freePoiStatus 为 FREE，此时显示「免费」）
    if (poi.ticketInfo && poi.ticketInfo.price) {
      const p = document.createElement('span');
      p.className = 'poi-price';
      p.textContent = poi.ticketInfo.price;
      priceBox.appendChild(p);
    } else if (poi.freePoiStatus === 'FREE') {
      const f = document.createElement('span');
      f.className = 'poi-free-tag';
      f.textContent = '免费';
      priceBox.appendChild(f);
    }
    priceRow.appendChild(priceBox);

    // 预订外链
    const safeJump = sanitizeHttpsUrl(poi.jumpUrl);
    if (safeJump) {
      const link = document.createElement('a');
      link.className = 'poi-book-link';
      link.href = safeJump;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = '去飞猪查看';
      priceRow.appendChild(link);
    }

    info.appendChild(priceRow);
    card.appendChild(info);
    return card;
  }

  /**
   * 3. 渲染体力账单 (逐段表格，只显示事实，无风险留空)
   */
  function renderStaminaBill(staminaDays) {
    if (!staminaDays || staminaDays.length === 0) {
      dom.staminaBillTbody.innerHTML = '<tr><td colspan="7" class="table-loading">暂无体力账单数据</td></tr>';
      return;
    }

    // 过滤天数
    let billItems = [];
    const activeDayIdx = state.selectedDayIndex === -1 ? 0 : state.selectedDayIndex;
    const targetDay = staminaDays[activeDayIdx] || staminaDays[0];

    // 更新过滤器按钮
    dom.billDayFilter.innerHTML = '';
    if (staminaDays.length > 1) {
      staminaDays.forEach((d, idx) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `day-tab-btn ${activeDayIdx === idx ? 'active' : ''}`;
        btn.textContent = `第 ${idx + 1} 天账单`;
        btn.addEventListener('click', () => {
          state.selectedDayIndex = idx;
          updateDayTabActiveState();
          renderComparisonColumns(state.currentData);
          renderStaminaBill(staminaDays);
        });
        dom.billDayFilter.appendChild(btn);
      });
    }

    billItems = targetDay.bill || [];
    dom.staminaBillTbody.innerHTML = '';

    if (billItems.length === 0) {
      dom.staminaBillTbody.innerHTML = '<tr><td colspan="7" class="table-loading">当日无路段计步记录</td></tr>';
      return;
    }

    const dayCap = targetDay.cap || 6000;

    billItems.forEach((item, idx) => {
      const tr = document.createElement('tr');

      // 1. 序号
      const tdIdx = document.createElement('td');
      tdIdx.textContent = String(idx + 1);
      tdIdx.style.color = '#8C8C8C';
      tdIdx.style.fontWeight = '600';
      tr.appendChild(tdIdx);

      // 2. 路段名称 (数据原文)
      const tdName = document.createElement('td');
      tdName.style.fontWeight = '700';
      tdName.textContent = item.name || '--';
      tr.appendChild(tdName);

      // 3. 出行方式 (直接使用数据中的 item.mode)
      const tdMode = document.createElement('td');
      const modeBadge = document.createElement('span');
      modeBadge.className = 'mode-badge';
      if (item.kind === 'transfer') {
        modeBadge.classList.add('taxi');
      } else if (item.kind === 'rest') {
        modeBadge.classList.add('rest');
      } else {
        modeBadge.classList.add('walk');
      }
      modeBadge.textContent = item.mode || '--';
      tdMode.appendChild(modeBadge);
      tr.appendChild(tdMode);

      // 4. 距离 / 步行米数
      const tdDist = document.createElement('td');
      let distText = '';
      if (item.kind === 'transfer') {
        distText = `${formatDistance(item.distance_m)}（步行约 ${Math.round(item.walking_m || 0)}m${item.estimated ? ' 估算' : ''}）`;
      } else if (item.kind === 'rest') {
        distText = item.walking_m > 0 ? `步行约 ${Math.round(item.walking_m)}m${item.estimated ? ' 估算' : ''}` : '0 m';
      } else {
        distText = `${formatDistance(item.walking_m || item.distance_m)}${item.estimated ? ' (估算)' : ''}`;
      }
      tdDist.textContent = distText;
      tr.appendChild(tdDist);

      // 5. 消耗步数
      const tdSteps = document.createElement('td');
      tdSteps.style.fontWeight = '700';
      if (item.steps === 0) {
        tdSteps.textContent = '0 步';
        tdSteps.style.color = '#00B578';
      } else {
        tdSteps.textContent = `+${formatNumber(item.steps)} 步${item.estimated ? ' (估算)' : ''}`;
      }
      tr.appendChild(tdSteps);

      // 6. 累计 / 上限
      const tdCum = document.createElement('td');
      const isOver = item.over_cap || item.cumulative_steps > dayCap;
      const pct = Math.round((item.cumulative_steps / dayCap) * 100);
      tdCum.className = isOver ? 'cum-over-cap' : '';
      tdCum.textContent = `${formatNumber(item.cumulative_steps)} / ${formatNumber(dayCap)} (${pct}%)`;
      tr.appendChild(tdCum);

      // 7. 风险与路况标注 (只显示数据里有的风险文字，没有风险就留空)
      const tdRisk = document.createElement('td');
      if (item.risk && String(item.risk).trim()) {
        const riskTag = document.createElement('span');
        riskTag.className = 'risk-tag warning';
        riskTag.textContent = item.risk;
        tdRisk.appendChild(riskTag);
      }
      tr.appendChild(tdRisk);

      dom.staminaBillTbody.appendChild(tr);
    });
  }

  /**
   * 4. 渲染酒店推荐卡 Hotel Card (只显示 hotel 里实际存在的字段)
   */
  function renderHotelCard(hotel, stay) {
    if (!hotel) {
      dom.hotelCardContainer.innerHTML = '<div class="hotel-skeleton">暂无推荐住宿数据</div>';
      return;
    }

    dom.hotelCardContainer.innerHTML = '';

    const card = document.createElement('div');
    card.className = 'hotel-main-card';

    // 酒店封面图
    const img = document.createElement('img');
    img.className = 'hotel-thumb';
    const safePic = sanitizeHttpsUrl(hotel.mainPic);
    img.src = safePic || 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="220" height="150" fill="%23eee"%3E%3Crect width="220" height="150"/%3E%3C/svg%3E';
    img.alt = hotel.name || '酒店外观';
    img.loading = 'lazy';
    img.onerror = function() {
      this.src = 'data:image/svg+xml;charset=utf-8,%3Csvg xmlns="http://www.w3.org/2000/svg" width="220" height="150" fill="%23f0f2f5"%3E%3Crect width="220" height="150"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-size="12" fill="%23999"%3E酒店图%3C/text%3E%3C/svg%3E';
    };
    card.appendChild(img);

    // 内容区
    const content = document.createElement('div');
    content.className = 'hotel-content';

    // 头部：名称与价格 (字段存在时显示)
    const headRow = document.createElement('div');
    headRow.className = 'hotel-head-row';

    if (hotel.name) {
      const name = document.createElement('h3');
      name.className = 'hotel-name';
      name.textContent = hotel.name;
      headRow.appendChild(name);
    }

    if (hotel.price) {
      const priceBox = document.createElement('div');
      priceBox.className = 'hotel-price-box';
      const price = document.createElement('div');
      price.className = 'hotel-price';
      price.textContent = hotel.price;
      priceBox.appendChild(price);
      headRow.appendChild(priceBox);
    }
    content.appendChild(headRow);

    // 标签与评分 (只显示 hotel 里实际存在的字段，无评分星级不显示)
    const metaRow = document.createElement('div');
    metaRow.className = 'hotel-meta-row';

    if (hotel.star && typeof hotel.star === 'string') {
      const star = document.createElement('span');
      star.className = 'hotel-badge star';
      star.textContent = hotel.star;
      metaRow.appendChild(star);
    }
    // flyai `rate` sits next to commission fields (likely a commission rate), not a review score; never show it.
    if (hotel.interestsPoi && typeof hotel.interestsPoi === 'string') {
      const poiTag = document.createElement('span');
      poiTag.className = 'hotel-badge';
      poiTag.textContent = hotel.interestsPoi;
      metaRow.appendChild(poiTag);
    }
    if (hotel.address && typeof hotel.address === 'string') {
      const addr = document.createElement('span');
      addr.className = 'hotel-badge';
      addr.style.maxWidth = '260px';
      addr.style.overflow = 'hidden';
      addr.style.textOverflow = 'ellipsis';
      addr.style.whiteSpace = 'nowrap';
      addr.textContent = hotel.address;
      metaRow.appendChild(addr);
    }
    if (metaRow.children.length > 0) {
      content.appendChild(metaRow);
    }

    // 住期（若存在 hotel_stay 字段）
    if (stay && stay.check_in && stay.check_out) {
      const datesBar = document.createElement('div');
      datesBar.className = 'hotel-dates-bar';
      datesBar.textContent = `📅 建议住期：${stay.check_in} 入住 · ${stay.check_out} 退房`;
      content.appendChild(datesBar);
    }

    // 推荐理由 (只显示 hotel.reason 原文，无对应字段不显示)
    if (hotel.reason && typeof hotel.reason === 'string') {
      const reasonBox = document.createElement('div');
      reasonBox.className = 'hotel-reason-box';
      reasonBox.textContent = `★ 推荐理由：${hotel.reason}`;
      content.appendChild(reasonBox);
    }

    // 预订外链按钮 (只在 detailUrl 存在时显示)
    const safeUrl = sanitizeHttpsUrl(hotel.detailUrl);
    if (safeUrl) {
      const actionRow = document.createElement('div');
      actionRow.className = 'hotel-action-row';
      const bookBtn = document.createElement('a');
      bookBtn.className = 'hotel-book-btn';
      bookBtn.href = safeUrl;
      bookBtn.target = '_blank';
      bookBtn.rel = 'noopener noreferrer';
      bookBtn.textContent = '去飞猪预订该酒店';
      actionRow.appendChild(bookBtn);
      content.appendChild(actionRow);
    }

    card.appendChild(content);
    dom.hotelCardContainer.appendChild(card);
  }

  /**
   * 5. 渲染智能体决策过程 (Tool Trace)
   * 只在返回数据里真有 tool_trace 时显示，没有就整块隐藏（也不显示占位）。
   * 每项字段是 {tool, args, n}：显示工具名 tool、参数 args 的简要键值、结果条数 n。不要自己写每一步的解说文字。
   * mode 为 "fallback" 时显示一行灰色提示「本次使用确定性规划兜底」并附原因字段（若有）。
   */
  function renderToolTrace(data) {
    const trace = data.tool_trace;
    const isFallback = data.mode === 'fallback';
    const hasTrace = Array.isArray(trace) && trace.length > 0;

    // Fallback 兜底提示
    if (dom.fallbackBanner) {
      if (isFallback) {
        const reason = data.fallback_reason || data.reason || '';
        dom.fallbackBanner.textContent = `本次使用确定性规划兜底${reason ? '（原因：' + reason + '）' : ''}`;
        dom.fallbackBanner.classList.remove('hidden');
      } else {
        dom.fallbackBanner.classList.add('hidden');
        dom.fallbackBanner.textContent = '';
      }
    }

    // tool_trace: 只在真有 tool_trace 时显示，没有就整块隐藏（也不显示占位）
    if (!hasTrace) {
      dom.toolTraceSection.classList.add('hidden');
      return;
    }

    dom.toolTraceSection.classList.remove('hidden');
    dom.traceStepCount.textContent = `${trace.length} 步`;

    if (dom.agentModeBadge) {
      dom.agentModeBadge.textContent = isFallback ? '确定性规划兜底' : 'Agent 决策链路';
    }

    dom.toolTraceTimeline.innerHTML = '';

    trace.forEach((step, idx) => {
      const li = document.createElement('li');
      li.className = 'timeline-item';

      const dot = document.createElement('div');
      dot.className = 'timeline-dot';
      li.appendChild(dot);

      const content = document.createElement('div');
      content.className = 'timeline-content';

      // 步骤头：工具名与结果条数 n
      const head = document.createElement('div');
      head.className = 'timeline-tool-head';

      const toolName = document.createElement('span');
      toolName.className = 'timeline-tool-name';
      toolName.textContent = `#${idx + 1} ${step.tool || step.tool_name || 'tool'}`;
      head.appendChild(toolName);

      // 结果标签只取 error / ok / n 字段
      let outcome = null;
      if (step.error) outcome = '已拒绝';
      else if (step.ok) outcome = '通过校验';
      else if (typeof step.n === 'number') outcome = step.tool === 'compute_stamina' ? `算出 ${step.n} 天` : `${step.n} 条结果`;
      if (outcome) {
        const badge = document.createElement('span');
        badge.className = 'timeline-result-badge';
        badge.textContent = outcome;
        head.appendChild(badge);
      }
      content.appendChild(head);
      if (step.error) {
        const err = document.createElement('div');
        err.className = 'timeline-args';
        err.style.color = '#c0392b';
        err.textContent = step.error;
        content.appendChild(err);
      }

      // 参数 args 的简要键值 (不写解说文字)
      const rawArgs = step.args || step.params || step.parameters;
      if (rawArgs) {
        const argsPre = document.createElement('div');
        argsPre.className = 'timeline-args';
        if (typeof rawArgs === 'object' && rawArgs !== null) {
          try {
            const entries = Object.entries(rawArgs)
              .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
              .join(', ');
            argsPre.textContent = entries || JSON.stringify(rawArgs);
          } catch (_) {
            argsPre.textContent = JSON.stringify(rawArgs);
          }
        } else {
          argsPre.textContent = String(rawArgs);
        }
        content.appendChild(argsPre);
      }

      li.appendChild(content);
      dom.toolTraceTimeline.appendChild(li);
    });

    if (state.traceExpanded) {
      dom.toolTraceBody.classList.remove('hidden');
      dom.toolTraceToggleHeader.classList.add('expanded');
    }
  }

  /**
   * 6. 渲染页脚提示与说明 (warnings, removed_claims, system_messages)
   */
  function renderFooterMeta(data) {
    // 1. removed_claims: 为空时不显示这块，非空时显示「已删除 N 条无依据描述」
    const removed = data.removed_claims;
    if (Array.isArray(removed) && removed.length > 0) {
      dom.claimsAuditBar.classList.remove('hidden');
      dom.claimsAuditBar.style.backgroundColor = '#FFFBE6';
      dom.claimsAuditBar.style.borderColor = '#FFE58F';
      dom.claimsAuditBar.style.color = '#D46B08';
      dom.claimsAuditText.textContent = `已删除 ${removed.length} 条无依据描述`;
    } else {
      dom.claimsAuditBar.classList.add('hidden');
      dom.claimsAuditText.textContent = '';
    }

    // 2. warnings: 原文逐条展示
    const warnings = data.warnings || [];
    dom.warningsList.innerHTML = '';
    if (warnings.length > 0) {
      warnings.forEach(w => {
        const li = document.createElement('li');
        li.textContent = w;
        dom.warningsList.appendChild(li);
      });
      dom.warningsBox.classList.remove('hidden');
    } else {
      dom.warningsBox.classList.add('hidden');
    }

    // 3. system_messages: 原样展示
    const sysMsgs = data.system_messages || [];
    if (sysMsgs.length > 0) {
      dom.systemMessagesBox.classList.remove('hidden');
      dom.systemMessagesPre.textContent = JSON.stringify(sysMsgs, null, 2);
    } else {
      dom.systemMessagesBox.classList.add('hidden');
      dom.systemMessagesPre.textContent = '';
    }
  }

  // 页面加载完成后启动
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

})();
