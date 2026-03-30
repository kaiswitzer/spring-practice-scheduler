import streamlit as st
import pandas as pd
from datetime import datetime, time
import io

# --- 1. OSU FOOTBALL BRANDING ---
st.set_page_config(page_title="OSU Football Practice Scheduler", layout="wide", page_icon="🏈")

st.markdown("""
    <style>
    /* BUTTON STYLING */
    .stButton>button, .stDownloadButton>button {
        background-color: #bb0000 !important;
        color: white !important;
        border-radius: 4px;
        font-weight: bold;
    }

    /* TITLES & SUBTITLES */
    .main-title { color: #bb0000; font-size: 42px; font-weight: bold; margin-bottom: 0px; }
    .sub-title { color: #666666; font-size: 20px; font-style: italic; margin-top: 0px; }
    
    /* LOGO ALIGNMENT */
    [data-testid="stVerticalBlock"] img {
        margin-top: -10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- LOGO & HEADER ---
col1, col2 = st.columns([1, 5])
with col1:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Ohio_State_Buckeyes_logo.svg/200px-Ohio_State_Buckeyes_logo.svg.png", width=100)
with col2:
    st.markdown('<p class="main-title">OHIO STATE FOOTBALL</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Spring Practice Staffing Operations</p>', unsafe_allow_html=True)

st.divider()

# --- 2. CORE SCHEDULING LOGIC ---
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

def get_availability_minutes(avail_string, start_m, end_m):
    if pd.isna(avail_string): return set()
    str_val = str(avail_string).strip().lower()
    
    if str_val in ["available all day!", "available all day", "all day"]:
        return set(range(start_m, end_m))
        
    if "not available" in str_val:
        return set()
        
    minutes = set()
    text = str_val.replace(';', '|').replace('and', '|').replace(',', '|')
    for seg in text.split('|'):
        if '-' in seg:
            try:
                parts = seg.split('-')
                start_t = parse_time(parts[0].strip())
                end_raw = parts[1].split('(')[0].strip()
                end_t = parse_time(end_raw)
                if start_t and end_t:
                    s, e = time_to_min(start_t), time_to_min(end_t)
                    s_clip = max(start_m, s)
                    e_clip = min(end_m, e)
                    if e_clip > s_clip:
                        for m in range(s_clip, e_clip): minutes.add(m)
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
                target_pool[best_person].discard(m)
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

# --- 3. TEMPLATE GENERATOR ---
def generate_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        example = {"Staff Name": ["Kai Switzer", "Madison Herbert"], "Availability": ["8am-4pm", "Available all day!"]}
        pd.DataFrame(example).to_excel(writer, index=False, sheet_name='Data_Entry')
        instr = {"Requirement": ["Times", "All Day", "Names"], "Instructions": ["8am-12pm", "Type 'Available all day!'", "Full Names only"]}
        pd.DataFrame(instr).to_excel(writer, index=False, sheet_name='Instructions')
    return output.getvalue()

# --- 4. MAIN PAGE SETTINGS (EXPANDABLE) ---
with st.expander("⚙️ SETTINGS & CONTROLS (Click to expand)"):
    st.subheader("📄 1. Get Template")
    st.download_button("📥 Download Excel Template", generate_template(), "OSU_Football_Template.xlsx")
    
    st.divider()
    st.subheader("🔑 2. Priority Staff")
    priority_input = st.text_area("Full names (comma separated):", 
        "Trenton Wells, Madison Herbert, Joaquin Lira, Elisabeth Christina Kearney, Kai Switzer, Reagan Butler, Emma Sherman")
    PRIORITY_NAMES = [p.strip() for p in priority_input.split(",") if p.strip()]
    
    st.divider()
    st.subheader("🏟️ 3. Lane Counts")
    num_col1, num_col2 = st.columns(2)
    with num_col1:
        num_recruit = st.number_input("Recruit Lanes:", value=8)
    with num_col2:
        num_floater = st.number_input("Floater Lanes:", value=5)

    st.divider()
    st.subheader("⏰ 4. Practice Times")
    p_col1, p_col2 = st.columns(2)
    with p_col1:
        practice_start = st.time_input("Practice Start Time:", value=time(6, 0))
    with p_col2:
        practice_end = st.time_input("Practice End Time:", value=time(16, 0))

    st.divider()
    st.subheader("⚖️ 5. Hour Constraints")
    min_hours = st.number_input("Minimum Hours per Staff Member:", value=2.0, step=0.5)

st.write("") 

# --- 5. MAIN PROCESSING ---
file = st.file_uploader("Upload Practice Availability", type="xlsx")

if file:
    raw_df = pd.read_excel(file)
    df = raw_df.dropna(subset=[raw_df.columns[0]])
    
    start_m = time_to_min(practice_start)
    end_m = time_to_min(practice_end)
    
    p_pool, o_pool = {}, {}
    warnings = []
    
    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        avail_str = str(row.iloc[1])
        
        # Check for times past practice end
        text = avail_str.strip().lower().replace(';', '|').replace('and', '|').replace(',', '|')
        for seg in text.split('|'):
            if '-' in seg:
                try:
                    parts = seg.split('-')
                    end_raw = parts[1].split('(')[0].strip()
                    end_t = parse_time(end_raw)
                    if end_t and time_to_min(end_t) > end_m:
                        warnings.append(f"🔍 **{name}** listed availability until {end_raw.upper()}, which exceeds the scheduled practice end time.")
                except: continue
                
        mins = get_availability_minutes(avail_str, start_m, end_m)
        if any(pn.lower() in name.lower() for pn in PRIORITY_NAMES):
            p_pool[name] = mins
        else: o_pool[name] = mins

    # Show warnings for data validation
    if warnings:
        with st.container():
            st.warning("⚠️ **Data Validation Alerts:** Possible typos found in the uploaded file.")
            for w in warnings:
                st.write(w)

    all_lanes = []
    for i in range(num_recruit):
        all_lanes.append({"type": f"Recruit Lane {i+1}", "data": build_lane_sticky(o_pool, p_pool, start_m, end_m)})
    for i in range(num_floater):
        all_lanes.append({"type": f"Floater Lane {i+1}", "data": build_lane_sticky(p_pool, o_pool, start_m, end_m)})

    # Generate dynamic blocks
    BLOCKS = []
    curr = start_m
    while curr < end_m:
        nxt = min(curr + 120, end_m)
        def fmt_time(minutes):
            h, m = minutes // 60, minutes % 60
            suffix = "AM" if h < 12 else "PM"
            display_h = h if h <= 12 else h - 12
            if display_h == 0: display_h = 12
            return f"{display_h}:{m:02d} {suffix}"
        BLOCKS.append((fmt_time(curr), fmt_time(nxt)))
        curr = nxt

    rows, staff_summary = [], {}

    for lane in all_lanes:
        r = {"Lane": lane['type']}
        for b_s, b_e in BLOCKS:
            r[f"{b_s}-{b_e}"] = format_cell(lane['data'], b_s, b_e)
        rows.append(r)
        
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

    st.divider()
    st.subheader("📋 Master Staffing Roster")
    st.write("Complete list of staff assignments:")
    
    roster_data = []
    for name, info in staff_summary.items():
        total_hrs = round(info["Total Hours"], 2)
        status = ""
        if total_hrs < min_hours:
            status = "⚠️ Under Minimum"
        roster_data.append({
            "Staff Member": name,
            "Total Hours": total_hrs,
            "Status": status,
            "Assigned Lanes": ", ".join(sorted(list(info["Lanes"])))
        })
    
    if roster_data:
        roster_df = pd.DataFrame(roster_data).sort_values("Staff Member")
        st.table(roster_df)
        
        # FINAL DOWNLOAD
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name='Schedule')
            roster_df.to_excel(writer, index=False, sheet_name='Staff_Roster')
        st.download_button("💾 Save Final Report to Excel", out.getvalue(), "OSU_Football_Report.xlsx")
    else:
        st.warning("No staff members could be scheduled. Check the availability format in your upload.")