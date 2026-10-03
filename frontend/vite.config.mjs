import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite 配置：https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    // 路径别名：@ 指向 src 目录。
    // 有了它，import 就从 "../../components/Sidebar.jsx" 变成 "@/components/Sidebar.jsx"。
    // 好处是文件挪位置时不用改一堆相对路径 —— 这也是 lab-agent 里同样的做法。
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },

  server: {
    port: 5173,

    // 监听地址。为什么不写 "localhost"（Vite 的默认值）：
    //   Vite 默认把 host 设成 "localhost"，Node 解析后只绑上了 IPv6 的 [::1]。
    //   结果就是 http://localhost:5173 能开、http://127.0.0.1:5173 却连不上 ——
    //   一旦浏览器或习惯走了 IPv4，页面直接白屏，而且报错信息很含糊、极难排查。
    //   设成 true = 监听本机所有网卡，IPv4 和 IPv6 都能连上，两个写法都对。
    //   附带好处：同一个局域网里的手机/平板也能用电脑的局域网 IP 访问。
    host: true,

    // 端口被占用时直接报错退出，而不是"悄悄换到 5174"。
    //   默认行为是自动找下一个空端口，这会造成"你以为服务在 5173、
    //   实际在 5174"的错觉，又是一轮白屏排查。宁可它当场报错。
    strictPort: true,

    // 开发代理。为什么需要它：
    //   浏览器有"同源策略" —— 前端跑在 5173、后端跑在 8000，端口不同就算跨源。
    //   虽然后端已经配了 CORS 白名单能放行，但走代理更干净：
    //   前端只管请求 "/api/ask"，Vite 在背后转给 8000 端口，
    //   浏览器眼里全程都是"同一个源"，不存在跨域问题。
    //   顺带好处：换后端地址时只改这里一行，前端代码一个字不用动。
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
