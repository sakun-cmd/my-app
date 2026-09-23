import { RaceList } from "@/components/RaceList";

export default function Home() {
  return (
    <>
      <section className="page-intro">
        <div>
          <p className="eyebrow">EXHIBITION DATA, EXPLAINED.</p>
          <h1>
            展示を、感覚だけで
            <br />
            終わらせない。
          </h1>
        </div>
        <p>
          展示タイム、スタート、進入の変化を同一条件で比較。
          <br />
          根拠をたどれる統計スコアで、判断材料を整理します。
        </p>
      </section>
      <section>
        <div className="section-heading">
          <div>
            <p className="eyebrow">RACE EXPLORER</p>
            <h2>レースを選ぶ</h2>
          </div>
        </div>
        <RaceList />
      </section>
    </>
  );
}

