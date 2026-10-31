import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  LoaderCircle,
  Leaf,
  type LucideIcon,
} from "lucide-react";
import { friendlyError, WriteKey } from "../api/client";
import { useSession } from "../state/session";
import { avatarImages } from "../assets";

export function Button({
  children,
  icon: Icon,
  loading,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: LucideIcon;
  loading?: boolean;
  variant?: string;
}) {
  return (
    <button
      {...props}
      disabled={loading || props.disabled}
      className={`button button-${variant} ${className}`}
    >
      {loading ? (
        <LoaderCircle className="spin" size={21} aria-hidden />
      ) : Icon ? (
        <Icon size={22} aria-hidden />
      ) : null}
      <span>{children}</span>
    </button>
  );
}
export function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "brand-small" : ""}`}>
      <span className="brand-mark">
        <Leaf size={20} strokeWidth={1.7} />
      </span>
      <span>
        银龄<small>VITA SENIOR</small>
      </span>
    </div>
  );
}
export function Page({
  title,
  subtitle,
  back,
  children,
  action,
  className = "",
}: {
  title: string;
  subtitle?: string;
  back?: string | false;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const navigate = useNavigate();
  return (
    <main className={`page ${className}`}>
      <header className="page-heading">
        {back !== false && (
          <button
            type="button"
            className="icon-button back"
            onClick={() => navigate(-1)}
            disabled={window.history.length <= 1}
            aria-label="返回上一页"
          >
            <ArrowLeft size={23} />
          </button>
        )}
        <div>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </main>
  );
}
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`card ${className}`}>{children}</section>;
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return error ? (
    <div className="notice notice-error" role="alert">
      <p>{friendlyError(error)}</p>
      {retry && (
        <button type="button" onClick={retry}>
          重新尝试
        </button>
      )}
    </div>
  ) : null;
}
export function Empty({
  title = "还没有记录",
  text = "生活里的小事，可以慢慢记下来。",
  children,
}: {
  title?: string;
  text?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark">
        <Leaf size={28} strokeWidth={1.3} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {children}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={25} className="spin" />
      <span>正在为您准备…</span>
    </div>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const generated = useId();
  const child = children as ReactElement<{
    id?: string;
    "aria-describedby"?: string;
  }>;
  const id = (isValidElement(child) && child.props.id) || generated;
  const control = isValidElement(child)
    ? cloneElement(child, {
        id,
        ...(hint ? { "aria-describedby": `${id}-hint` } : {}),
      })
    : children;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {control}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  );
}
export function Success({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="notice notice-success">
      <Check size={19} />
      <span>{children}</span>
    </div>
  );
}
export function MenuLink({
  to,
  icon: Icon,
  title,
  text,
  children,
}: {
  to: string;
  icon: LucideIcon;
  title: string;
  text?: string;
  children?: ReactNode;
}) {
  return (
    <Link to={to} className="menu-link">
      <span className="menu-icon">
        <Icon size={23} strokeWidth={1.6} />
      </span>
      <span>
        <strong>{title}</strong>
        {text && <small>{text}</small>}
      </span>
      {children}
      <ArrowRight size={19} className="muted" />
    </Link>
  );
}
export function Avatar({
  state = "idle",
  className = "",
}: {
  state?: string;
  className?: string;
}) {
  const image = avatarImages[state] || avatarImages.idle;
  return (
    <div
      className={`avatar-orb avatar-${state} ${className}`}
      role="img"
      aria-label={`小银龄${state === "listening" ? "正在聆听" : state === "speaking" ? "正在播报" : state === "thinking" ? "正在思考" : ""}${image ? "" : "，中性形象占位"}`}
    >
      {image ? (
        <img src={image} alt="小银龄" />
      ) : (
        <>
          <div className="orb-inner">
            <Leaf strokeWidth={1.1} />
            <span>小银龄</span>
          </div>
          <span className="orb-shine" />
        </>
      )}
    </div>
  );
}

export function useResource<T>(
  key: string,
  load: () => Promise<T>,
  refreshToken: unknown = 0,
) {
  const loader = useRef(load);
  loader.current = load;
  const [state, setState] = useState<{
    key: string;
    data?: T;
    error?: unknown;
    loading: boolean;
  }>({ key, loading: true });
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const id = ++generation.current;
    setState((old) => ({
      key,
      data: old.key === key ? old.data : undefined,
      loading: true,
    }));
    try {
      const data = await loader.current();
      if (id === generation.current) setState({ key, data, loading: false });
    } catch (error) {
      if (id === generation.current)
        setState((old) => ({ ...old, key, error, loading: false }));
    }
  }, [key]);
  useEffect(() => {
    void refresh();
    return () => {
      generation.current++;
    };
  }, [refresh, refreshToken]);
  return {
    data: state.key === key ? state.data : undefined,
    error: state.key === key ? state.error : null,
    loading: state.key !== key || state.loading,
    refresh,
  };
}
export function useAction() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const key = useRef(new WriteKey()),
    running = useRef(false);
  const run = async <T,>(
    action: (keys: WriteKey) => Promise<T>,
  ): Promise<T | undefined> => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      return await action(key.current);
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      running.current = false;
      setBusy(false);
    }
  };
  return { busy, error, run, clearError: () => setError(null) };
}
