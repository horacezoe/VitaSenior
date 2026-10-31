import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { useData } from "../state/data";
import { rewardImages } from "../assets";

export function EggBasket() {
  const { ledger, dailyReport } = useData(),
    basket = useRef<HTMLImageElement>(null);
  const [count, setCount] = useState(0),
    [message, setMessage] = useState("每一份认真，都值得被看见");
  useEffect(() => {
    if (!ledger) return;
    let alive = true,
      running = false,
      retry: ReturnType<typeof setTimeout> | undefined;
    let current: Animation | null = null;
    const refresh = () =>
      setCount(
        ledger.read().filter((proof) => proof.played || !proof.queued).length,
      );
    const animate = async () => {
      if (!alive || running) return;
      running = true;
      const work = async () => {
        while (alive && ledger.pending().length) {
          const proof = ledger.pending()[0];
          if (
            !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
            basket.current
          ) {
            const egg = document.createElement("img");
            egg.src = rewardImages.egg;
            egg.alt = "";
            egg.className = "reward-flying";
            document.body.appendChild(egg);
            const frames = () => {
              const rect = basket.current!.getBoundingClientRect();
              return [
                {
                  transform: `translate(${Math.max(28, rect.left - 100)}px, ${Math.max(80, rect.top - 180)}px) scale(1)`,
                  opacity: 0,
                },
                { offset: 0.12, opacity: 1 },
                {
                  transform: `translate(${rect.left + rect.width * 0.42}px, ${rect.top + rect.height * 0.38}px) scale(.23)`,
                  opacity: 0,
                },
              ];
            };
            current = egg.animate(frames(), {
              duration: 1050,
              easing: "cubic-bezier(.3,.05,.38,1)",
              fill: "forwards",
            });
            const resize = () =>
              current?.effect &&
              (current.effect as KeyframeEffect).setKeyframes(frames());
            window.addEventListener("resize", resize);
            try {
              await current.finished;
            } catch {
              /* Leaving home preserves the queued reward. */
            }
            window.removeEventListener("resize", resize);
            egg.remove();
            current = null;
          }
          if (alive) {
            ledger.complete(proof.id);
            refresh();
            setMessage("新记录已保存，收获一枚鸡蛋");
            window.dispatchEvent(new Event("vitasenior:rewards"));
          }
        }
      };
      try {
        if (navigator.locks) {
          await navigator.locks.request(
            ledger.key,
            { ifAvailable: true },
            async (lock) => {
              if (lock) await work();
              else
                retry = setTimeout(() => {
                  running = false;
                  void animate();
                }, 350);
            },
          );
        } else await work();
      } finally {
        running = false;
        refresh();
      }
    };
    const update = () => {
      refresh();
      void animate();
    };
    update();
    window.addEventListener("vitasenior:rewards", update);
    window.addEventListener("storage", update);
    return () => {
      alive = false;
      current?.cancel();
      clearTimeout(retry);
      window.removeEventListener("vitasenior:rewards", update);
      window.removeEventListener("storage", update);
    };
  }, [ledger]);
  const shown = dailyReport?.reward_summary?.cumulative ?? count;
  return (
    <section className="egg-garden" aria-label="打卡鸡蛋奖励">
      <div className="egg-copy">
        <span className="eyebrow">
          <Sparkles size={14} />
          我的攒鸡蛋进度
        </span>
        <p>
          <strong>{shown}</strong>
          <span>枚鸡蛋</span>
        </p>
        <small role="status" aria-live="polite">
          {message}
        </small>
      </div>
      <div className="basket-art">
        {shown > 0 && (
          <img className="basket-egg egg-one" src={rewardImages.egg} alt="" />
        )}
        {shown > 1 && (
          <img className="basket-egg egg-two" src={rewardImages.egg} alt="" />
        )}
        <img
          ref={basket}
          className="basket-image"
          src={rewardImages.basket}
          alt="鸡蛋篮子，中性素材占位"
        />
      </div>
    </section>
  );
}
