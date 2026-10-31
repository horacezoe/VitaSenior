import { it,expect,vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import Login from "../src/pages/Login";
vi.mock("../src/state/session",()=>({useSession:()=>({api:{},role:"elder",setRole:()=>{},login:()=>{},connectionError:false})}));
it("shows normal login without persona selector, fictional-data copy, or preset verification code",()=>{
 const html=renderToStaticMarkup(<MemoryRouter><Login /></MemoryRouter>);
 expect(html).toContain("手机号码");expect(html).toContain("获取验证码");
 expect(html).not.toMatch(/演示|虚构|123456|选择人物|连接与体验设置/);
});
