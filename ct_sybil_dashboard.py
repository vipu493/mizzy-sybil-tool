"""
Mizzy Tool - CT Sybil Deep Research Dashboard
=============================================
English UI · Mobile-friendly · Claims · Funding · Withdrawals

Run:
    pip install streamlit pandas requests networkx pyvis plotly numpy
    python -m streamlit run ct_sybil_dashboard.py --server.port 8015 --server.headless true

Open: http://localhost:8015
"""

import streamlit as st
import pandas as pd
import requests
import time
import networkx as nx
from pyvis.network import Network
import plotly.express as px
from collections import Counter, defaultdict
from datetime import datetime
import tempfile
import os

st.set_page_config(
    page_title="Mizzy Tool | CT Sybil Research",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background: linear-gradient(180deg, #0a0a0f 0%, #111118 100%); }
    .main-header {
        font-size: clamp(1.6rem, 5vw, 2.6rem); font-weight: 800;
        background: linear-gradient(90deg, #00d4ff, #7b2cbf, #ff006e);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        text-align: center; margin-bottom: 0.2rem;
    }
    .sub-header {
        text-align: center; color: #888;
        font-size: clamp(0.85rem, 2.5vw, 1.05rem); margin-bottom: 1.2rem;
    }
    div[data-testid="stMetricValue"] { font-size: clamp(1.1rem, 3vw, 1.7rem); font-weight: 700; }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] {
        background: #1a1a24; border-radius: 8px;
        padding: 0.4rem 0.9rem; font-size: 0.9rem;
    }
    @media (max-width: 768px) {
        .stTabs [data-baseweb="tab"] { padding: 0.35rem 0.6rem; font-size: 0.8rem; }
        .block-container { padding: 0.8rem 0.6rem; }
    }
    .info-box {
        background: #1a1a24; border-left: 3px solid #00d4ff;
        padding: 0.8rem 1rem; border-radius: 8px; margin: 0.5rem 0;
        color: #ccc; font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

CT_TOKEN = "0x5A642BE07e166C3F23EFAb23E47972a68d3E220a"
DISTRIBUTOR = "0x3Ef3D8bA38EBe18DB133cEc108f4D14CE00Dd9Ae"
CHAIN_ID = 1
API_BASE = "https://api.etherscan.io/v2/api"


def api_get(params, timeout=35):
    r = requests.get(API_BASE, params=params, timeout=timeout)
    return r.json()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_claims(api_key: str, start_block: int = 26085000, end_block: int = 0, chunk: int = 2000):
    all_claims, seen = [], set()
    dist = DISTRIBUTOR.lower()
    if end_block <= 0:
        try:
            data = api_get({"chainid": CHAIN_ID, "module": "proxy", "action": "eth_blockNumber", "apikey": api_key})
            end_block = int(data.get("result", "0x0"), 16)
        except Exception:
            end_block = start_block + 250000

    progress = st.progress(0, text="Fetching claims by block range...")
    span = max(1, end_block - start_block)
    cursor, windows, empty_streak = start_block, 0, 0

    while cursor <= end_block and windows < 500:
        hi = min(cursor + chunk - 1, end_block)
        page, got = 1, 0
        while page <= 12:
            params = {
                "chainid": CHAIN_ID, "module": "account", "action": "tokentx",
                "contractaddress": CT_TOKEN, "address": DISTRIBUTOR,
                "startblock": cursor, "endblock": hi,
                "page": page, "offset": 1000, "sort": "asc", "apikey": api_key,
            }
            try:
                data = api_get(params)
                results = data.get("result", [])
                if not isinstance(results, list) or not results:
                    break
                for t in results:
                    if t.get("from", "").lower() != dist:
                        continue
                    h = t.get("hash")
                    if not h or h in seen:
                        continue
                    seen.add(h)
                    all_claims.append(t)
                    got += 1
                if len(results) < 1000:
                    break
                page += 1
                time.sleep(0.22)
            except Exception as e:
                st.warning(f"Blocks {cursor}-{hi}: {e}")
                break
        windows += 1
        empty_streak = empty_streak + 1 if got == 0 else 0
        progress.progress(min(0.99, (hi - start_block) / span),
                          text=f"Blocks {cursor:,}–{hi:,} → {len(all_claims):,} claims")
        cursor = hi + 1
        time.sleep(0.18)
        if empty_streak >= 15 and len(all_claims) > 500:
            break
    progress.empty()
    return all_claims


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_eth_funding(api_key: str, address: str, max_pages: int = 3):
    funders, addr = [], address.lower()
    for page in range(1, max_pages + 1):
        params = {
            "chainid": CHAIN_ID, "module": "account", "action": "txlist",
            "address": address, "page": page, "offset": 100, "sort": "asc", "apikey": api_key,
        }
        try:
            data = api_get(params, timeout=25)
            results = data.get("result", [])
            if not isinstance(results, list) or not results:
                break
            for tx in results:
                if (tx.get("to", "").lower() == addr
                        and int(tx.get("value", 0)) > 0
                        and tx.get("from", "").lower() != addr):
                    funders.append({
                        "from": tx["from"].lower(),
                        "value_eth": int(tx["value"]) / 1e18,
                        "hash": tx["hash"],
                        "timeStamp": int(tx.get("timeStamp", 0)),
                    })
            if len(results) < 100:
                break
            time.sleep(0.2)
        except Exception:
            break
    return funders


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ct_withdrawals(api_key: str, address: str, max_pages: int = 3):
    """Outbound CT transfers from a claim wallet (where tokens were sent after claim)."""
    outs, addr = [], address.lower()
    for page in range(1, max_pages + 1):
        params = {
            "chainid": CHAIN_ID, "module": "account", "action": "tokentx",
            "contractaddress": CT_TOKEN, "address": address,
            "page": page, "offset": 100, "sort": "asc", "apikey": api_key,
        }
        try:
            data = api_get(params, timeout=25)
            results = data.get("result", [])
            if not isinstance(results, list) or not results:
                break
            for t in results:
                if t.get("from", "").lower() != addr:
                    continue
                to = t.get("to", "").lower()
                if to == addr or to == DISTRIBUTOR.lower():
                    continue
                # Skip burn / zero address — not a real withdrawal destination
                if to in ("0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"):
                    continue
                outs.append({
                    "to": to,
                    "value_ct": int(t.get("value", 0)) / 1e18,
                    "hash": t.get("hash"),
                    "timeStamp": int(t.get("timeStamp", 0)),
                    "blockNumber": int(t.get("blockNumber", 0)),
                })
            if len(results) < 100:
                break
            time.sleep(0.2)
        except Exception:
            break
    return outs


def process_claims(claims: list):
    if not claims:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    for t in claims:
        rows.append({
            "txhash": t.get("hash"),
            "block": int(t.get("blockNumber", 0)),
            "timestamp": int(t.get("timeStamp", 0)),
            "from": t.get("from", "").lower(),
            "to": t.get("to", "").lower(),
            "value_ct": int(t.get("value", 0)) / 1e18,
            "datetime": datetime.utcfromtimestamp(int(t.get("timeStamp", 0))).strftime("%Y-%m-%d %H:%M"),
        })
    df = pd.DataFrame(rows)
    agg = (
        df.groupby("to")
        .agg(
            claims=("txhash", "count"),
            total_ct=("value_ct", "sum"),
            first_claim=("datetime", "min"),
            last_claim=("datetime", "max"),
            unique_blocks=("block", "nunique"),
            max_single=("value_ct", "max"),
        )
        .reset_index()
        .sort_values("claims", ascending=False)
        .reset_index(drop=True)
    )
    agg.columns = ["wallet", "claims", "total_ct", "first_claim", "last_claim", "unique_blocks", "max_single"]
    return df, agg


def build_network_graph(agg_df, funding_map, withdrawal_map, min_claims=5, max_nodes=700):
    G = nx.DiGraph()
    top = agg_df[agg_df["claims"] >= min_claims].head(150)

    for _, row in top.iterrows():
        w = row["wallet"]
        G.add_node(
            w,
            label=f"{w[:6]}…{w[-4:]}\n{int(row['claims'])}",
            title=f"{w}\nClaims: {int(row['claims'])}\nCT: {row['total_ct']:.1f}",
            group="sybil", size=min(14 + row["claims"] * 0.3, 50), color="#ff006e",
        )

    for wallet, funders in funding_map.items():
        if wallet not in G:
            continue
        for f in funders[:20]:
            funder = f["from"]
            if funder not in G:
                G.add_node(funder, label=f"{funder[:6]}…{funder[-4:]}",
                           title=f"Funder {funder}\n{f['value_eth']:.5f} ETH",
                           group="funder", size=13, color="#00d4ff")
            G.add_edge(funder, wallet, title=f"{f['value_eth']:.5f} ETH", color="#00d4ff70", width=1.1)

    for wallet, outs in withdrawal_map.items():
        if wallet not in G:
            continue
        for o in outs[:20]:
            dest = o["to"]
            if dest not in G:
                G.add_node(dest, label=f"{dest[:6]}…{dest[-4:]}",
                           title=f"Withdrawal dest {dest}\n{o['value_ct']:.2f} CT",
                           group="withdraw", size=16, color="#ffcc00")
            G.add_edge(wallet, dest, title=f"{o['value_ct']:.2f} CT", color="#ffcc0070", width=1.2)

    if G.number_of_nodes() > max_nodes:
        deg = dict(G.degree())
        keep = sorted(deg, key=deg.get, reverse=True)[:max_nodes]
        G = G.subgraph(keep).copy()
    return G


def render_pyvis_graph(G, height="720px"):
    net = Network(height=height, width="100%", bgcolor="#0a0a0f", font_color="#e0e0e0", directed=True)
    net.from_nx(G)
    net.set_options("""
    {
      "nodes": {"borderWidth": 2, "font": {"size": 11}},
      "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.45}}, "smooth": {"type": "continuous"}},
      "physics": {
        "forceAtlas2Based": {"gravitationalConstant": -70, "centralGravity": 0.01, "springLength": 110},
        "solver": "forceAtlas2Based", "stabilization": {"iterations": 120}
      },
      "interaction": {"hover": true, "navigationButtons": true}
    }
    """)
    path = os.path.join(tempfile.gettempdir(), "sybil_graph.html")
    net.save_graph(path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("## Controls")
    api_key = st.text_input("Etherscan API Key", value="HFTCSGHR3JKAKVS1QYAP1U1NSXEYHQGH9T", type="password")

    st.markdown("---")
    st.markdown("### Claim Fetch")
    start_block = st.number_input("Start block", value=26085000, step=1000)
    end_block = st.number_input("End block (0 = latest)", value=0, step=1000)
    chunk = st.slider("Block chunk size", 500, 8000, 2000)
    min_claims = st.slider("Min claims = Sybil", 2, 50, 5)

    st.markdown("---")
    st.markdown("### Deep Trace")
    enable_funding = st.checkbox("Trace ETH funding (gas sponsors)", value=True)
    enable_withdraw = st.checkbox("Trace CT withdrawals (destinations)", value=True)
    trace_limit = st.slider("Max wallets to deep-trace", 10, 200, 60)
    big_threshold = st.number_input("Big claim threshold (CT)", value=1000.0, step=100.0)

    st.markdown("---")
    fetch_btn = st.button("FETCH & ANALYZE", use_container_width=True, type="primary")
    st.caption("CT 0x5A64…220a · Distributor 0x3Ef3…d9Ae")

# ==================== HEADER ====================
st.markdown('<div class="main-header">Mizzy Tool</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">CT Airdrop · Sybil · Funding · Withdrawals · Big Claims</div>',
    unsafe_allow_html=True,
)

if "claims_df" not in st.session_state:
    st.session_state.claims_df = None
    st.session_state.agg_df = None
    st.session_state.funding_map = {}
    st.session_state.withdrawal_map = {}
    st.session_state.funder_index = {}
    st.session_state.dest_index = {}

# ==================== FETCH ====================
if fetch_btn:
    if not api_key:
        st.error("API key required")
    else:
        with st.spinner("Fetching claims..."):
            claims = fetch_claims(api_key, int(start_block), int(end_block), int(chunk))
            if not claims:
                st.error("No claims found.")
            else:
                df, agg = process_claims(claims)
                st.session_state.claims_df = df
                st.session_state.agg_df = agg
                st.success(f"{len(df):,} claims · {len(agg):,} unique wallets")

                targets = agg[agg["claims"] >= min_claims].head(trace_limit)["wallet"].tolist()
                if not targets:
                    targets = agg.head(min(trace_limit, 30))["wallet"].tolist()

                funding_map, withdrawal_map = {}, {}

                if enable_funding or enable_withdraw:
                    prog = st.progress(0, text="Deep tracing wallets...")
                    for i, w in enumerate(targets):
                        if enable_funding:
                            fl = fetch_eth_funding(api_key, w, max_pages=3)
                            if fl:
                                funding_map[w] = fl
                        if enable_withdraw:
                            wl = fetch_ct_withdrawals(api_key, w, max_pages=3)
                            if wl:
                                withdrawal_map[w] = wl
                        prog.progress((i + 1) / max(1, len(targets)), text=f"Trace {i+1}/{len(targets)}")
                        time.sleep(0.15)
                    prog.empty()

                st.session_state.funding_map = funding_map
                st.session_state.withdrawal_map = withdrawal_map

                funder_index = defaultdict(list)
                for w, flist in funding_map.items():
                    for f in flist:
                        funder_index[f["from"]].append({"wallet": w, "eth": f["value_eth"]})
                st.session_state.funder_index = dict(funder_index)

                dest_index = defaultdict(list)
                for w, olist in withdrawal_map.items():
                    for o in olist:
                        dest_index[o["to"]].append({"wallet": w, "ct": o["value_ct"]})
                st.session_state.dest_index = dict(dest_index)

                st.success(
                    f"Funding: {len(funding_map)} wallets · "
                    f"Withdrawals: {len(withdrawal_map)} wallets · "
                    f"Common funders: {sum(1 for v in funder_index.values() if len(v)>=2)} · "
                    f"Common destinations: {sum(1 for v in dest_index.values() if len(v)>=2)}"
                )

# ==================== DASHBOARD ====================
if st.session_state.agg_df is not None:
    agg = st.session_state.agg_df
    df = st.session_state.claims_df
    funding_map = st.session_state.funding_map
    withdrawal_map = st.session_state.withdrawal_map
    funder_index = st.session_state.funder_index
    dest_index = st.session_state.dest_index

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Claims", f"{len(df):,}")
    c2.metric("Unique Wallets", f"{len(agg):,}")
    c3.metric(f"Sybil (≥{min_claims})", f"{len(agg[agg['claims'] >= min_claims])}")
    c4.metric("Biggest Cluster", f"{int(agg.iloc[0]['claims'])} claims")
    c5.metric("Sybil CT Vol", f"{agg[agg['claims'] >= min_claims]['total_ct'].sum():,.0f}")

    st.markdown("---")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Top Sybil",
        "Big Claims",
        "Funding",
        "Withdrawals",
        "Graph",
        "Raw",
    ])

    # TAB 1
    with tab1:
        st.subheader("Multi-Claim Recipients")
        filtered = agg[agg["claims"] >= min_claims].copy()
        filtered["total_ct"] = filtered["total_ct"].round(2)
        filtered["max_single"] = filtered["max_single"].round(2)
        st.dataframe(filtered, use_container_width=True, height=400)
        st.download_button("Download Sybil CSV", filtered.to_csv(index=False), "ct_sybil_wallets.csv", "text/csv")

        if len(filtered):
            selected = st.selectbox("Deep dive wallet", filtered["wallet"].tolist(), key="sybil_sel")
            st.markdown(f"[Etherscan](https://etherscan.io/address/{selected})")
            wrow = filtered[filtered["wallet"] == selected].iloc[0]
            a, b, c = st.columns(3)
            a.metric("Claims", int(wrow["claims"]))
            b.metric("Total CT", f"{wrow['total_ct']:.2f}")
            c.metric("Max Single", f"{wrow['max_single']:.2f}")
            w_claims = df[df["to"] == selected].sort_values("timestamp")
            if not w_claims.empty:
                fig = px.scatter(w_claims, x="datetime", y="value_ct",
                                 title=f"Claims · {selected[:12]}…",
                                 color_discrete_sequence=["#ff006e"])
                fig.update_layout(template="plotly_dark", paper_bgcolor="#0a0a0f", height=300)
                st.plotly_chart(fig, use_container_width=True)

    # TAB 2 Big Claims
    with tab2:
        st.subheader("Large Individual Claims")
        st.markdown(
            f'<div class="info-box">Claims ≥ <b>{big_threshold:,.0f} CT</b>. Flag if recipient is also a multi-claim collector.</div>',
            unsafe_allow_html=True,
        )
        big = df[df["value_ct"] >= big_threshold].sort_values("value_ct", ascending=False).copy()
        if big.empty:
            st.info("No claims above threshold.")
        else:
            claim_map = dict(zip(agg["wallet"], agg["claims"]))
            big["recipient_claims"] = big["to"].map(claim_map)
            big["is_sybil_collector"] = big["recipient_claims"].fillna(0) >= min_claims
            st.metric("Big claims", f"{len(big):,}")
            st.dataframe(
                big[["datetime", "to", "value_ct", "recipient_claims", "is_sybil_collector", "txhash"]],
                use_container_width=True, height=380,
            )
            st.download_button("Download Big Claims", big.to_csv(index=False), "ct_big_claims.csv", "text/csv")

    # TAB 3 Funding
    with tab3:
        st.subheader("ETH Funding Chains (Gas Sponsors)")
        if not funding_map:
            st.info("Enable funding trace and re-fetch.")
        else:
            common = [(f, len(ws)) for f, ws in funder_index.items() if len(ws) >= 2]
            common.sort(key=lambda x: -x[1])
            st.write(f"Traced **{len(funding_map)}** wallets · **{len(funder_index)}** funders · "
                     f"**{len(common)}** common funders (2+ wallets)")
            if common:
                cdf = pd.DataFrame(common, columns=["funder", "wallets_funded"])
                st.dataframe(cdf.head(60), use_container_width=True, height=300)
                st.download_button("Download Common Funders", cdf.to_csv(index=False), "ct_common_funders.csv", "text/csv")
                sel = st.selectbox("Inspect funder", [x[0] for x in common[:50]], key="fund_sel")
                st.markdown(f"[Etherscan](https://etherscan.io/address/{sel})")
                for item in funder_index[sel]:
                    st.code(f"{item['wallet']}  ←  {item['eth']:.6f} ETH")
            else:
                st.caption("No shared funders yet — increase trace limit.")

    # TAB 4 Withdrawals — KEY NEW FEATURE
    with tab4:
        st.subheader("CT Withdrawal Destinations")
        st.markdown(
            '<div class="info-box"><b>Sybil signal:</b> many different claim wallets sending CT to the <b>same</b> address or exchange = same entity consolidating funds.</div>',
            unsafe_allow_html=True,
        )
        if not withdrawal_map:
            st.info("Enable withdrawal trace and re-fetch.")
        else:
            common_dest = [(d, len(ws), sum(x["ct"] for x in ws)) for d, ws in dest_index.items() if len(ws) >= 2]
            common_dest.sort(key=lambda x: (-x[1], -x[2]))
            st.write(
                f"Traced withdrawals from **{len(withdrawal_map)}** wallets · "
                f"**{len(dest_index)}** destinations · "
                f"**{len(common_dest)}** shared destinations (2+ claim wallets)"
            )
            if common_dest:
                ddf = pd.DataFrame(common_dest, columns=["destination", "source_wallets", "total_ct_in"])
                ddf["total_ct_in"] = ddf["total_ct_in"].round(2)
                st.dataframe(ddf.head(80), use_container_width=True, height=320)
                st.download_button(
                    "Download Shared Destinations", ddf.to_csv(index=False),
                    "ct_shared_destinations.csv", "text/csv",
                )
                sel_d = st.selectbox("Inspect destination", [x[0] for x in common_dest[:50]], key="dest_sel")
                st.markdown(f"[Etherscan](https://etherscan.io/address/{sel_d})")
                st.markdown("**Claim wallets that withdrew here:**")
                for item in sorted(dest_index[sel_d], key=lambda x: -x["ct"]):
                    st.code(f"{item['wallet']}  →  {item['ct']:.2f} CT")
            else:
                st.caption("No shared withdrawal destinations yet — increase trace limit or wait for more post-claim transfers.")

            # Per-wallet withdrawal view
            st.markdown("### Per-wallet withdrawals")
            wsel = st.selectbox("Wallet", list(withdrawal_map.keys())[:100] if withdrawal_map else [], key="wout_sel")
            if wsel and wsel in withdrawal_map:
                odf = pd.DataFrame(withdrawal_map[wsel])
                st.dataframe(odf, use_container_width=True, height=220)

    # TAB 5 Graph
    with tab5:
        st.subheader("Network Graph")
        st.caption("Pink = multi-claim · Cyan = funders · Gold = withdrawal destinations")
        if funding_map or withdrawal_map:
            with st.spinner("Building graph..."):
                G = build_network_graph(agg, funding_map, withdrawal_map, min_claims=min_claims)
                st.write(f"**{G.number_of_nodes()}** nodes · **{G.number_of_edges()}** edges")
                html = render_pyvis_graph(G)
                st.components.v1.html(html, height=740, scrolling=True)
        else:
            st.info("Enable funding/withdrawal trace for full graph.")
            fig = px.bar(agg.head(20), x="wallet", y="claims", title="Top 20 collectors",
                         color="claims", color_continuous_scale="magma")
            fig.update_layout(template="plotly_dark", paper_bgcolor="#0a0a0f", xaxis_tickangle=-45, height=380)
            st.plotly_chart(fig, use_container_width=True)

    # TAB 6 Raw
    with tab6:
        st.subheader("Raw Data")
        st.dataframe(df.head(1000), use_container_width=True, height=380)
        st.download_button("All Claims CSV", df.to_csv(index=False), "ct_all_claims.csv", "text/csv")
        st.download_button("Wallet Aggregate CSV", agg.to_csv(index=False), "ct_wallet_agg.csv", "text/csv")

else:
    st.info("Set options in the sidebar → **FETCH & ANALYZE**")
    st.markdown("""
    ### Features
    1. **All claims** (block-range, bypasses 10k API cap)
    2. **Multi-claim sybil collectors**
    3. **Big single claims**
    4. **ETH funding chains** (common gas sponsors)
    5. **CT withdrawal destinations** — many claim wallets → same address = sybil consolidation
    6. **Network graph** (claims + funders + withdrawals)
    7. Mobile-friendly · English UI · GitHub-ready
    """)
