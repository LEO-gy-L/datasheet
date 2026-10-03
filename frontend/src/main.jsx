import { StrictMode } from "react";

import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App.jsx";
import { AuthProvider } from "@/context/AuthContext.jsx";
import { theme } from "@/theme.js";

import "@/assets/css/global.css";

/**
 * 前端入口 —— 只做"装配"，不定义任何视觉。
 *
 * 这一层跟后端 main.py 的角色一模一样：把零件接起来，然后启动。
 * 接的是四层，从外到内：
 *
 *   ConfigProvider  给所有 Ant Design 组件注入全局配置（中文语言包 + 视觉主题）
 *   AntdApp         antd 用来承载 message / modal 的上下文容器。
 *                   不用它的话，message.success() 这种静态调用会弹警告
 *                   "Static function can not consume context"，
 *                   而且换主题时弹窗不会跟着变。
 *   BrowserRouter   路由模式：地址栏是 /admin/users 这种"真路径"，
 *                   而不是 /#/admin/users。需要后端配合把未知路径都返回 index.html
 *                   （开发阶段 Vite 已经处理好了，不用管）。
 *   AuthProvider    全局登录态。任何组件里 useAuth() 就能拿到当前用户。
 *
 * 颜色 / 圆角 / 间距这些值全在 src/theme.js —— 想改视觉去那个文件，
 * 这个文件不用动。
 */
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntdApp>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  </StrictMode>
);
