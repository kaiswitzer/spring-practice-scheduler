import streamlit as st
import pandas as pd
from datetime import datetime, time
import io

# --- 1. OSU FOOTBALL BRANDING ---
st.set_page_config(page_title="OSU Football Practice Scheduler", layout="wide", page_icon="🏈")

st.markdown("""
    <style>
    .stButton>button, .stDownloadButton>button {
        background-color: #bb0000 !important;
        color: white !important;
        border-radius: 4px;
        font-weight: bold;
    }
    .main-title { color: #bb0000; font-size: 42px; font-weight: bold; margin-bottom: 0px; }
    .sub-title { color: #666666; font-size: 20px; font-style: italic; margin-top: 0px; }
    /* Visual "Settings" hint */
    [data-testid="stSidebarNav"]::before {
        content: "SETTINGS ⚙️";
        margin-left: 20px;
        margin-top: 20px;
        font-size: 1.5rem;
        font-weight: bold;
        color: #bb0000;
    }
    </style>
    """, unsafe_allow_html=True)

col1, col2 = st.columns([1, 5])
with col1:
    st.image("https://brand.osu.edu/assets/site/logo.png", width=100)
with col2:
    st.markdown('<p class="main-title">OHIO STATE FOOTBALL</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Spring Practice Staffing Operations</p>', unsafe_allow_html=True)

# --- 2. TEMPLATE GENERATOR ---
def generate_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        example = {"Staff Name": ["Kai Switzer", "Madison Herbert"], "Availability": ["8am-4pm", "6am-10am; 2pm-4pm"]}
        pd.DataFrame(example).to_excel(writer, index=False, sheet_name='Data_Entry')
        instr = {"Format": ["Times", "Names"], "Notes": ["Use AM/PM (8am-12pm)", "Use Full Names only"]}
        pd.DataFrame(instr).to_excel(writer, index=False, sheet_name='Instructions')
    return output.getvalue()

# --- 3. SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("📋 Admin Controls")
    st.download_button("📥 Download Excel Template", generate_template(), "OSU_Football_Template.xlsx")
    
    st.divider()
    priority_input = st.text_area("Priority Staff (Full Names):", 
        "Trenton Wells, Madison Herbert, Joaquin Lira, Elisabeth Christina Kearney, Kai Switzer, Reagan Butler, Emma Sherman")
    PRIORITY_NAMES = [p.strip() for p in priority_input.split(",") if p.strip()]
    
    num_recruit = st.number_input("Recruit Lanes:", value=8)
    num_floater = st.number_input("Floater Lanes:", value=5)

# --- 4. CORE SCHEDULING LOGIC ---
# (Keep your existing parse_time, time_to_min, get_availability_minutes, and build_lane_sticky functions here)
# [Paste those 4 functions from your previous code here]

# --- 5. MAIN PROCESSING ---
file = st.file_uploader("Upload Practice Availability", type="xlsx")

if file:
    raw_df = pd.read_excel(file)
    df = raw_df.dropna(subset=[raw_df.columns[0]])
    
    p_pool, o_pool = {}, {}
    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        mins = get_availability_minutes(row.iloc[1])
        if any(pn.lower() in name.lower() for pn in PRIORITY_NAMES):
            p_pool[name] = mins
        else: o_pool[name] = mins

    all_lanes = []
    for i in range(num_recruit):
        all_lanes.append({"type": f"Recruit Lane {i+1}", "data": build_lane_sticky(o_pool, p_pool, 360, 960)})
    for i in range(num_floater):
        all_lanes.append({"type": f"Floater Lane {i+1}", "data": build_lane_sticky(p_pool, o_pool, 360, 960)})

    # DISPLAY TABLE
    BLOCKS = [("6:00 AM", "8:00 AM"), ("8:00 AM", "10:00 AM"), ("10:00 AM", "12:00 PM"), ("12:00 PM", "2:00 PM"), ("2:00 PM", "4:00 PM")]
    rows = []
    staff_summary = {} # To track who is working where

    for lane in all_lanes:
        r = {"Lane": lane['type']}
        for b_s, b_e in BLOCKS:
            r[f"{b_s}-{b_e}"] = format_cell(lane['data'], b_s, b_e)
        rows.append(r)
        
        # Build the Roster List
        for seg in lane['data']:
            if seg['name'] != 'GAP':
                name = seg['name']
                duration = (seg['end'] - seg['start']) / 60
                if name not in staff_summary:
                    staff_summary[name] = {"Total Hours": 0, "Lanes": set()}
                staff_summary[name]["Total Hours"] += duration
                staff_summary[name]["Lanes"].add(lane['type'])

    st.subheader("🏈 Generated Practice Grid")
    st.dataframe(pd.DataFrame(rows).style.map(style_gaps), use_container_width=True)

    # --- 6. MASTER STAFF ROSTER ---
    st.divider()
    st.subheader("📋 Master Staffing Roster")
    st.write("Complete list of everyone scheduled for today's practice:")
    
    roster_data = []
    for name, info in staff_summary.items():
        roster_data.append({
            "Staff Member": name,
            "Total Hours": round(info["Total Hours"], 2),
            "Assigned Lanes": ", ".join(sorted(list(info["Lanes"])))
        })
    
    roster_df = pd.DataFrame(roster_data).sort_values("Staff Member")
    st.table(roster_df) # Using st.table for a clean, non-scrollable list

    # DOWNLOAD FINAL
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name='Schedule')
        roster_df.to_excel(writer, index=False, sheet_name='Staff_Roster')
    st.download_button("💾 Save Full Report to Excel", out.getvalue(), "OSU_Football_Practice_Report.xlsx")