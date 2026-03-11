import streamlit as st
import pandas as pd
from datetime import datetime, time
import io

# --- 1. OSU BRANDING & THEME (Scarlet & Gray) ---
st.set_page_config(page_title="Buckeye Practice Scheduler", layout="wide", page_icon="🌰")

# Custom CSS for the "Settings" label and OSU look
st.markdown("""
    <style>
    /* Change Button Colors to Scarlet */
    .stButton>button, .stDownloadButton>button {
        background-color: #bb0000 !important;
        color: white !important;
        border-radius: 8px;
        border: none;
    }
    /* Main Header Styling */
    .main-title {
        color: #bb0000;
        font-size: 50px;
        font-weight: bold;
        border-bottom: 5px solid #666666;
        margin-bottom: 20px;
    }
    /* Sidebar "Settings" Label Override */
    section[data-testid="stSidebar"] .st-emotion-cache-10oheav {
        display: flex;
        flex-direction: column-reverse;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. MAIN PAGE CONTENT ---
col1, col2 = st.columns([1, 4])
with col1:
    # Official OSU Logo from Web (will work on GitHub)
    st.image("https://brand.osu.edu/assets/site/logo.png", width=120)
with col2:
    st.markdown('<p class="main-title">🌰 Buckeye Practice Scheduler</p>', unsafe_allow_html=True)
    st.markdown("### *Fisher College of Business | Staffing Logistics*")

st.divider()

# --- 3. TEMPLATE GENERATOR ---
def generate_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        example_data = {
            "Staff Full Name": ["Kai Switzer", "Madison Herbert", "Brutus Buckeye"],
            "Availability": ["8am-12pm; 2pm-4pm", "9:00 AM - 4:00 PM", "6am-10am"]
        }
        pd.DataFrame(example_data).to_excel(writer, index=False, sheet_name='Practice_Availability')
        instr_data = {"Guide": ["Use AM/PM", "Use Full Names"], "Instructions": ["e.g. 8am-4pm", "Matches Priority List"]}
        pd.DataFrame(instr_data).to_excel(writer, index=False, sheet_name='INSTRUCTIONS')
    return output.getvalue()

# --- 4. SIDEBAR (The "Settings" Area) ---
with st.sidebar:
    # Visual "Settings" Header for users
    st.markdown("# ⚙️ SETTINGS")
    st.write("---")
    
    st.subheader("📄 1. Get Template")
    st.download_button("Download Excel Template", generate_template(), "OSU_Template.xlsx")
    
    st.subheader("🔑 2. Priority Staff")
    default_priority = "Trenton Wells, Madison Herbert, Joaquin Lira, Elisabeth Christina Kearney, Kai Switzer, Reagan Butler, Emma Sherman"
    priority_input = st.text_area("Full names:", default_priority)
    PRIORITY_FULL_NAMES = [p.strip() for p in priority_input.split(",") if p.strip()]
    
    st.subheader("🏟️ 3. Lane Counts")
    num_recruit_lanes = st.number_input("Recruit Lanes:", value=8)
    num_floater_lanes = st.number_input("Floater Lanes:", value=5)

# --- CORE LOGIC FUNCTIONS ---
def parse_time(t_str):
    if not t_str or pd.isna(t_str): return None
    t_str = str(t_str).strip().upper().replace('.', '')
    if any(x in t_str for x in ["EOD", "END", "4PM", "4:00PM"]):
        return time(16, 0)
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M", "%H"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            continue
    return None

def time_to_min(t):
    return t.hour * 60 + t.minute

def get_availability_minutes(avail_string):
    if pd.isna(avail_string) or "Not Available" in str(avail_string):
        return set()
    minutes = set()
    text = str(avail_string).replace(';', '|').replace('and', '|').replace(',', '|')
    for seg in text.split('|'):
        if '-' in seg:
            try:
                parts = seg.split('-')
                start_t = parse_time(parts[0].strip())
                end_raw = parts[1].split('(')[0].strip()
                end_t = parse_time(end_raw)
                if start_t and end_t:
                    s, e = time_to_min(start_t), time_to_min(end_t)
                    if e > s:
                        for m in range(s, e): minutes.add(m)
            except: continue
    return minutes

def build_lane_sticky(primary_pool, secondary_pool, start_min, end_min):
    lane_schedule = []
    curr = start_min
    last_person = None
    while curr < end_min:
        best_person = None
        target_pool = None
        for pool in [primary_pool, secondary_pool]:
            if last_person in pool and curr in pool[last_person]:
                best_person = last_person
                target_pool = pool
                break
        if not best_person:
            longest_stretch = -1
            for pool in [primary_pool, secondary_pool]:
                for name, mins in pool.items():
                    if curr in mins:
                        stretch = 0
                        for m in range(curr, end_min):
                            if m in mins: stretch += 1
                            else: break
                        if stretch > longest_stretch:
                            longest_stretch = stretch
                            best_person = name
                            target_pool = pool
                if best_person: break 

        if best_person:
            stretch = 0
            for m in range(curr, end_min):
                if m in target_pool[best_person]: stretch += 1
                else: break
            seg_end = curr + stretch
            lane_schedule.append({'name': best_person, 'start': curr, 'end': seg_end})
            for m in range(curr, seg_end):
                target_pool[best_person].remove(m)
            last_person = best_person
            curr = seg_end
        else:
            next_start = end_min
            for p in [primary_pool, secondary_pool]:
                for mins in p.values():
                    future = [m for m in mins if m > curr]
                    if future: next_start = min(next_start, min(future))
            lane_schedule.append({'name': 'GAP', 'start': curr, 'end': next_start})
            last_person = None
            curr = next_start
    return lane_schedule

def format_cell(lane_data, b_start_str, b_end_str):
    s_m, e_m = time_to_min(parse_time(b_start_str)), time_to_min(parse_time(b_end_str))
    entries = []
    for seg in lane_data:
        overlap_s, overlap_e = max(s_m, seg['start']), min(e_m, seg['end'])
        if overlap_s < overlap_e:
            h1, m1 = (overlap_s // 60), (overlap_s % 60)
            h2, m2 = (overlap_e // 60), (overlap_e % 60)
            t1 = f"{(h1-1)%12+1}:{m1:02d}"
            t2 = f"{(h2-1)%12+1}:{m2:02d}"
            entries.append(f"{seg['name']} ({t1}-{t2})")
    return " / ".join(entries) if entries else "⚠️ GAP"

def style_gaps(val):
    color = '#ff4b4b33' if isinstance(val, str) and "⚠️ GAP" in val else ''
    return f'background-color: {color}'

# --- MAIN APP PROCESSING ---
file = st.file_uploader("Upload Availability Excel", type="xlsx")

if file:
    raw_df = pd.read_excel(file)
    df = raw_df.dropna(subset=[raw_df.columns[0]])
    
    priority_pool, others_pool = {}, {}

    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        mins = get_availability_minutes(row.iloc[1])
        is_priority = any(p_name.lower() in name.lower() for p_name in PRIORITY_FULL_NAMES)
        
        if is_priority:
            priority_pool[name] = mins
        else:
            others_pool[name] = mins

    final_lanes = []
    for i in range(num_recruit_lanes):
        data = build_lane_sticky(others_pool, priority_pool, 360, 960)
        final_lanes.append({"type": f"Recruit Lane {i+1}", "data": data})
    
    for i in range(num_floater_lanes):
        data = build_lane_sticky(priority_pool, others_pool, 360, 960)
        final_lanes.append({"type": f"Floater Lane {i+1}", "data": data})

    BLOCKS = [("6:00 AM", "8:00 AM"), ("8:00 AM", "10:00 AM"), ("10:00 AM", "12:00 PM"), ("12:00 PM", "2:00 PM"), ("2:00 PM", "4:00 PM")]
    table_rows, warnings = [], []
    
    for lane in final_lanes:
        row = {"Lane": lane['type']}
        for b_start, b_end in BLOCKS:
            row[f"{b_start}-{b_end}"] = format_cell(lane['data'], b_start, b_end)
        for seg in lane['data']:
            if seg['name'] == 'GAP':
                warnings.append(f"Coverage Alert: {lane['type']} has unfilled time.")
        table_rows.append(row)

    res_df = pd.DataFrame(table_rows)
    st.subheader("🏈 Generated Practice Schedule")
    st.dataframe(res_df.style.map(style_gaps), use_container_width=True)

    if warnings:
        with st.expander("🚩 Coverage Alerts"):
            for w in sorted(list(set(warnings))):
                st.write(f"- {w}")

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        res_df.to_excel(writer, index=False)
    
    st.divider()
    st.download_button("💾 Save Final Schedule to Excel", out.getvalue(), "Buckeye_Practice_Schedule.xlsx")