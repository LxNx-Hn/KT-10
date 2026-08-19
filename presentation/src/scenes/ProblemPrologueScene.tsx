export function ProblemPrologueScene() {
  return (
    <main className="prologue-scene">
      <img
        className="prologue-photo"
        src="/problem/problem-city.png"
        alt="같은 도시 거리와 대중교통 환경에서 서로 다른 이동 부담이 생기는 장면"
        style={{ objectPosition: '42% 62%' }}
      />

      <div className="prologue-overlay" />

      <section className="prologue-copy">
        <h2 className="type-scene-title">
          같은 도시에서도, 이동 부담은
          <br />
          사람마다 달라집니다.
        </h2>
        <p className="type-body">
          보행·환승·시설·환경 조건이 같은 목적지까지의 경험을 바꿉니다.
        </p>
      </section>

      <p className="prologue-caption">AI 생성 콘셉트 이미지</p>

      <div className="presentation-help">
        <span>SPACE</span>
        <span>진행</span>
        <span className="help-divider">·</span>
        <span>←</span>
        <span>이전</span>
        <span className="help-divider">·</span>
        <span>F</span>
        <span>전체화면</span>
      </div>
    </main>
  );
}
