/**
 * 全站视觉主题（极简高级灰）
 * ========================
 * 这是**全站唯一的一份视觉定义**。为什么从 main.jsx 里搬出来：
 *   原来它跟"装配路由 / 登录态"的代码混在一起，211 行里 155 行是色彩数值 ——
 *   想改个灰阶得先在一堆 <ConfigProvider> 标签里翻半天。
 *   搬到独立文件之后，main.jsx 只剩"把哪几层套起来"这一件事。
 *
 * ---------------------------------------------------------------------------
 * 为什么主题放在 JS 里，而基础样式放在 global.css 里
 * ---------------------------------------------------------------------------
 * 这是本文件存在的前提，值得先说清楚：
 *
 *   · antd 组件的颜色 / 圆角 / 间距，一律走这里的 token。
 *     因为 antd 内部用 CSS-in-JS 生成样式，它生成的 <style> 插在 <head> 里、
 *     优先级压过普通 CSS 文件。你想用 CSS 覆盖它，得写一堆 !important，
 *     还会跟它的状态类名（hover / active / disabled）打架。
 *     与其对抗，不如直接告诉它"该用什么值"。
 *
 *   · 页面底色、字体栈、滚动条这种"框架级"的东西，留在 global.css。
 *     那些跟 antd 无关，写 CSS 变量更直观。
 *
 * 色板用的是 **zinc 灰阶**（比纯 #ccc 那种灰多一点点冷调，看起来更"贵"）。
 * 全站不出现任何彩色 —— 强调色就是近黑 #18181B，主按钮黑底白字。
 * 这是极简系的标准做法（Vercel / Linear 都这么干）。
 */

/** antd 的颜色、圆角、间距令牌。改一个值，所有组件跟着走。 */
const token = {
  // ---------------------------------------------------------------- 主色
  // 主色 = 近黑。改这一个值，按钮、选中态、链接、开关全部跟着走。
  colorPrimary: "#18181B",
  // colorInfo 单独列出来，是因为 antd 给它的默认值是**蓝色 #1677ff**。
  // 不写它，界面上任何一处"信息色"（Alert / Badge / Progress…）都会冒出蓝色；
  // 写了它，这类组件将来被引入时也是灰的。属于"当前没人用、但删了会留雷"的一条。
  colorInfo: "#18181B",

  // ---------------------------------------------------------------- 文字
  // 文字分三级。为什么不用纯黑 #000：纯黑压在浅灰底上对比太硬，
  // 看久了累，而且没有层次 —— 三级灰才能拉开"标题 / 正文 / 辅助"。
  colorText: "#18181B",
  colorTextSecondary: "#52525B",
  colorTextTertiary: "#A1A1AA",
  colorTextQuaternary: "#D4D4D8",

  // ---------------------------------------------------------------- 线与底
  // 极简系靠 **1px 细边框** 分层，而不是靠阴影，
  // 所以边框色必须比 antd 默认的更淡、更冷。
  colorBorder: "#E4E4E7",
  colorBorderSecondary: "#F0F0F2",
  colorBgLayout: "#FAFAFA",
  colorFillSecondary: "#F4F4F5",

  // ---------------------------------------------------------------- 形状
  // 圆角收到 8、控件高度收到 34。圆角越大越"可爱"，越小越"专业" ——
  // 高级感来自克制。
  borderRadius: 8,
  controlHeight: 34,
  lineHeight: 1.6,

  // ---------------------------------------------------------------- 阴影
  // 几乎不用。只保留"浮起来的东西"需要的一点点 ——
  // 而"浮起来的东西"刚好有三种，所以这三条各有用处（都有实测）：
  //   boxShadow          弹窗（Modal）
  //   boxShadowSecondary 下拉菜单（Dropdown）
  //   boxShadowTertiary  分段控件选中的那一片（Segmented）
  boxShadow: "0 1px 2px rgba(9, 9, 11, .04)",
  boxShadowSecondary: "0 6px 20px rgba(9, 9, 11, .10)",
  boxShadowTertiary: "0 1px 2px rgba(9, 9, 11, .03)",

  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", ' +
    '"Hiragino Sans GB", "Microsoft YaHei", sans-serif',
};

/**
 * 组件级微调。
 *
 * 原则：只覆盖"和 antd 默认观感差别最大"的几处，其余交给上面的 token 自动派生 ——
 * 少写一个值，以后就少一处不一致。
 *
 * 这里每写一个组件名，就等于承诺"这个组件会在界面上出现"。
 * 所以下面每个块都对应着某个真实渲染出来的东西，注释里写明了是哪个。
 * （曾经配了 InputNumber，但项目里从头到尾没引入过这个组件 —— 已删。）
 */
const components = {
  // 骨架：顶栏白、侧栏白，靠细线分开。
  // 覆盖的是 antd 默认的"深色侧栏"，这是全局观感差别最大的一处。
  // bodyBg 不用写：它的默认值就是 colorBgLayout，而上面已经把那个令牌设成了 #FAFAFA。
  Layout: {
    headerBg: "#FFFFFF",
    siderBg: "#FFFFFF",
    headerHeight: 56,
    headerPadding: "0 20px",
    triggerBg: "#FFFFFF",
  },

  // 菜单：选中态用"浅灰底 + 深色字"，不用彩条。
  Menu: {
    itemBg: "transparent",
    subMenuItemBg: "transparent",
    itemColor: "#52525B",
    itemHoverBg: "#F4F4F5",
    itemHoverColor: "#18181B",
    itemSelectedBg: "#F4F4F5",
    itemSelectedColor: "#18181B",
    itemHeight: 38,
    itemMarginInline: 8,
    itemMarginBlock: 2,
    itemBorderRadius: 6,
    // 关掉 antd 默认那条**右侧蓝色竖条**。它是整套界面里最"廉价"的一笔，
    // 灰阶系统用底色变化表示选中，已经够了。
    activeBarBorderWidth: 0,
    iconMarginInlineEnd: 10,
  },

  // 卡片：头部去掉 antd 默认的浅灰分隔，跟内容一起白成一片，靠外框分层
  Card: {
    headerBg: "#FFFFFF",
    headerFontSize: 15,
    paddingLG: 20,
    colorBorderSecondary: "#E9E9EC",
  },

  // 表格：表头浅灰、行 hover 极淡、去掉竖分隔线
  Table: {
    headerBg: "#FAFAFA",
    headerColor: "#52525B",
    headerSplitColor: "transparent",
    borderColor: "#F0F0F2",
    rowHoverBg: "#FAFAFA",
    cellPaddingBlock: 12,
    cellPaddingInline: 14,
  },

  // 按钮：不要投影（antd 默认那圈彩色光晕在灰阶里很跳），字重 500 更有精神
  Button: {
    fontWeight: 500,
    primaryShadow: "none",
    defaultShadow: "none",
    dangerShadow: "none",
    defaultBorderColor: "#D4D4D8",
    defaultColor: "#3F3F46",
  },

  // 标签：默认就是浅灰底 + 中灰字
  Tag: {
    defaultBg: "#F4F4F5",
    defaultColor: "#52525B",
  },

  // 分段控件（管理员/用户「问题反馈」页顶部那个状态切块）：
  // 凹槽浅灰、选中块白 —— 像一块嵌进去的滑块
  Segmented: {
    trackBg: "#F4F4F5",
    trackPadding: 3,
    itemColor: "#52525B",
    itemSelectedBg: "#FFFFFF",
    itemSelectedColor: "#18181B",
    itemHoverColor: "#18181B",
  },

  // 输入框聚焦：一圈极淡的黑。
  // 这一条只在**聚焦时**才看得见 —— 静止状态测不出来，必须真的点进去才验得到。
  // 不配的话 antd 会画一圈又黑又细的环（rgba(3,4,12,.67) / 2px），
  // 在浅灰界面上像画了个记号，很跳。
  Input: {
    activeBorderColor: "#18181B",
    hoverBorderColor: "#A1A1AA",
    activeShadow: "0 0 0 3px rgba(9, 9, 11, .06)",
  },

  // 下拉选项（助理页反馈弹窗里的「问题分类」）
  // 注意 optionSelectedBg 必须留着：它的默认值是 controlItemBgActive，
  // 在近黑主色下推导出来是 #56575c —— 选中项会变成一坨深灰，非常难看。
  Select: {
    optionSelectedBg: "#F4F4F5",
  },

  // 弹窗：标题栏要白底。antd 的默认值是 'transparent'，
  // 不写它标题栏会透出底下的灰，跟内容糊在一起。
  Modal: {
    headerBg: "#FFFFFF",
  },

  // 顶栏头像的下拉菜单：行距比默认松一点点
  Dropdown: {
    paddingBlock: 6,
  },
};

/** 交给 main.jsx 的 <ConfigProvider theme={theme}> */
export const theme = { token, components };

/* ============================================================================
   审计记录：2026-10-03 清掉 13 条"写了等于没写"的配置
   ============================================================================
   起因是一句质疑："之前肯定有好多没用的"。静态 grep 查不出来 ——
   token 不是被 import 的，它由 antd 内部消费，完全可能"名字在、界面上什么都没变"。

   所以做了两件事来验：
     ① **删了试**：逐条删掉，遍历 12 个页面（含聚焦 / 弹窗展开 / 下拉展开三个交互态），
        把每个元素的 computedStyle 抓成指纹跟基线逐行比对。零差异 → 删。
     ② **对账**：直接问 antd 的令牌推导引擎"这条不写的话兜底是什么值"。
        兜底值跟我们写的一模一样 → 删。

   删掉的 13 条（每条都同时满足上面两条）：
     token.fontSize            14 = antd 默认值
     token.borderRadiusLG      兜底 = borderRadius + 2 = 10，完全一致
     token.borderRadiusSM      兜底 = borderRadius - 2 = 6，完全一致
     token.colorLink           兜底 = colorPrimary = #18181B，完全一致
     token.colorBgContainer    兜底 #ffffff，同一个颜色
     token.colorFillQuaternary 兜底 rgba(0,0,0,.02) 铺在白底上正好是 #FAFAFA
     components.Layout.bodyBg   兜底 = colorBgLayout = #FAFAFA（上面那条令牌已在管）
     components.Menu.groupTitleColor  全项目没有菜单分组，那个元素从未出现
     components.Table.footerBg        全项目没有表格页脚，那个元素从未出现
     components.InputNumber     项目从未引入这个组件
     components.Select.optionSelectedColor  兜底 = colorText = #18181B
     components.Modal.titleFontSize         兜底 = fontSizeHeading5 = 16
     components.Descriptions    唯一用法既没 title 也没 bordered，两个属性双双落空

   反过来说，**有几条看着也没人用，但坚决不能删** —— 它们是防雷的：
     colorInfo         兜底是**蓝色 #1677ff**。删了它，将来任何一处 info 色都爆蓝。
     Modal.headerBg    兜底是 transparent，删了标题栏会透出灰底
     Select.optionSelectedBg  兜底是 #56575c，删了选中项变一坨深灰
     Input.activeShadow      兜底是 rgba(3,4,12,.67) / 2px 的黑环
     boxShadow 三条    分别被 Modal / Dropdown / Segmented 真实使用（静止态看不出来）
     fontFamily        1600+ 个元素在用，只是中文环境下浏览器换了字形、肉眼不易察觉

   教训：**判断"有没有用"必须真的删一次再看，而且要把交互态也算进去。**
   只看静止画面会把 Input 的聚焦环、Dropdown 的展开面全部误判成"没用"。
   ============================================================================ */
