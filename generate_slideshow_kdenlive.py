from datetime import datetime
import os
import sys
import random
from pathlib import Path

# =============================
# Configuration
# =============================
FPS = 25
TRANSITION_SECONDS = 1
PROFILE = "atsc_1080p_25"

TRANSITIONS = [
    "luma",          # klassische Überblendung
    "mix",           # einfache Dissolve
    "wipe",          # Wischblende
    "slide",         # Schieben
    "composite",      # Überlagerung
]

# helper: format frames to Kdenlive time string HH:MM:SS.mmm
def format_time_from_frames(frames: int) -> str:
    total_seconds = frames / FPS
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int(round((total_seconds - int(total_seconds)) * 1000))
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

# =============================
# Parameter Validation
# =============================
if len(sys.argv) < 3:
    print("Usage: python generate_slideshow_kdenlive.py <image_folder> <display_duration> [music_file]")
    sys.exit(1)

image_folder = Path(sys.argv[1])
duration_seconds = float(sys.argv[2])
music_file = Path(sys.argv[3]) if len(sys.argv) >= 4 else None

if not image_folder.exists():
    print("Image folder does not exist.")
    sys.exit(1)

images = sorted([
    f for f in image_folder.iterdir()
    if f.suffix.lower() in [".jpg", ".jpeg", ".png"]
])

if not images:
    print("No images found.")
    sys.exit(1)

duration_frames = int(duration_seconds * FPS)
transition_frames = int(TRANSITION_SECONDS * FPS)

kdenliveid = 1
# =============================
# XML Start
# =============================
xml = f'''<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" producer="main_bin" root="{image_folder}" version="7.32.0">
<profile colorspace="709" description="HD 1080p 25 fps" display_aspect_den="9" display_aspect_num="16" frame_rate_den="1" frame_rate_num="25" height="1080" progressive="1" sample_aspect_den="1" sample_aspect_num="1" width="1920"/>
'''

# =============================
# Black Background Producer
# =============================
total_duration_frames = (duration_frames * len(images)) + (transition_frames * (len(images) - 1))
total_duration_time = format_time_from_frames(total_duration_frames)
xml += f'''
<producer id="producer_black" in="00:00:00.000" out="{total_duration_time}">
  <property name="length">2147483647</property>
  <property name="eof">continue</property>
  <property name="resource">black</property>
  <property name="aspect_ratio">1</property>
  <property name="mlt_service">color</property>
  <property name="kdenlive:playlistid">black_track</property>
  <property name="mlt_image_format">rgba</property>
  <property name="set.test_audio">0</property>
  <property name="kdenlive:id">{kdenliveid}</property>
</producer>
'''
kdenliveid += 1

producers = {}
# =============================
# Image Producers
# =============================
for i, img in enumerate(images):
    duration_time = format_time_from_frames(duration_frames)
    xml += f'''
<producer id="producer{i}" in="00:00:00.000" out="{duration_time}">
  <property name="resource">{img.resolve()}</property>
  <property name="length">{duration_frames}</property>
  <property name="ttl">25</property>
  <property name="aspect_ratio">1</property>
  <property name="format">1</property>
  <property name="kdenlive:duration">{duration_time}</property>
  <property name="kdenlive:monitorPosition">0</property>
  <property name="kdenlive:id">{kdenliveid}</property>
</producer>
'''
    # write info also as a dict for the main_bin playlist
    producers[i] = {
        "id": kdenliveid,
        "resource": img.resolve(),
        "duration": duration_time,
        "producer_id": f"producer{i}",
        "length": duration_frames,
    }
    kdenliveid += 1

# =============================
# Playlists
# =============================
if music_file and music_file.exists():
    xml += f'''
  <producer id="music">
    <property name="resource">{music_file.resolve()}</property>
    <property name="kdenlive:id">{kdenliveid}</property>
  </producer>
'''
    kdenliveid += 1

# =============================
# Playlist Video
# =============================
# For transitions, we need to create two playlists, alternating the entries to allow for overlapping during transitions.


# one playlist:
# <playlist id="playlist2">
#  <entry in="00:00:00.000" out="00:00:04.960" producer="producer1">
#   <property name="kdenlive:id">6</property>
#  </entry>
#  <blank length="00:00:02.400"/>
#  <entry in="00:00:00.000" out="00:00:04.960" producer="producer4">
#   <property name="kdenlive:id">7</property>
#  </entry>
# </playlist>
#
# the other playlist:
#<playlist id="playlist4">
#  <blank length="00:00:03.760"/>
#  <entry in="00:00:00.000" out="00:00:04.960" producer="producer2">
#   <property name="kdenlive:id">5</property>
#  </entry>
# </playlist>
#
# transitions will be 1 second long, so we need to have the first picture in the first playlist, then the second picture in the second playlist, and so on, alternating. The blank length will be the duration of the picture minus the transition time for the first picture, and for the subsequent pictures, it will be the duration of the picture minus the transition time minus 1 second (for the transition itself).
#
# so, we will have this:
# picture 1: playlist 0, entry 0, duration: duration_seconds, blanklength 0 
# picture 2: playlist 1, entry 0, duration: duration_seconds, blanklength duration_seconds-1
# picture 3: playlist 0, entry 1, duration: duration_seconds, blanklength duration_seconds-1-1
# picture 4: playlist 1, entry 1, duration: duration_seconds, blanklength duration_seconds-1-1
# and so on...

# create an array for the playlists
playlists = ["", ""]
playlists[0] = f'<playlist id="playlist0">\n  <property name="kdenlive:id">{kdenliveid}</property>'
kdenliveid += 1
playlists[1] = f'<playlist id="playlist1">\n  <property name="kdenlive:id">{kdenliveid}</property>'
kdenliveid += 1

for i in range(len(images)):
    playlist_id = i % 2

    # For playlist entries use in at 0 and out as clip duration (producer internal range)
    if i == 0:
      blank_length = "00:00:00.000"
    elif i == 1:
      blank_length_seconds = duration_seconds - TRANSITION_SECONDS 
      # convert seconds to frames and then to time format
      blank_length_frames = int(blank_length_seconds * FPS)
      blank_length = format_time_from_frames(blank_length_frames)
    else:
      blank_length_seconds = duration_seconds - TRANSITION_SECONDS - TRANSITION_SECONDS
      blank_length_frames = int(blank_length_seconds * FPS)
      blank_length = format_time_from_frames(blank_length_frames)
    
    playlists[playlist_id] += f"\n  <blank length=\"{blank_length}\"/>"
    playlists[playlist_id] += f"\n  <entry in=\"00:00:00.000\" out=\"{duration_time}\" producer=\"producer{i}\"/>\n"

playlists[0] += '\n</playlist>\n'
playlists[1] += '\n</playlist>\n'

xml += playlists[0]
xml += playlists[1]


# ===============================
# playlist main_bin
# ===============================
some_uuid = f"{random.randint(1000000000000, 9999999999999)}"
another_uuid = f"{random.randint(1000000000000, 9999999999999)}"
sequence_folder_number = random.randint(1, 1000)

xml += f'''<playlist id="main_bin">
  <property name="kdenlive:folder.-1.2">Sequenzen</property>
  <property name="kdenlive:sequenceFolder">{sequence_folder_number}</property>
  <property name="kdenlive:docproperties.activetimeline">{some_uuid}</property>
  <property name="kdenlive:docproperties.audioChannels">2</property>
  <property name="kdenlive:docproperties.binsort">0</property>
  <property name="kdenlive:docproperties.browserurl">{image_folder}</property>
  <property name="kdenlive:docproperties.documentid">1770905335333</property>
  <property name="kdenlive:docproperties.enableTimelineZone">0</property>
  <property name="kdenlive:docproperties.enableexternalproxy">0</property>
  <property name="kdenlive:docproperties.enableproxy">0</property>
  <property name="kdenlive:docproperties.externalproxyparams">./;;.LRV;./;;.MP4</property>
  <property name="kdenlive:docproperties.generateimageproxy">0</property>
  <property name="kdenlive:docproperties.generateproxy">0</property>
  <property name="kdenlive:docproperties.kdenliveversion">25.12.2</property>
  <property name="kdenlive:docproperties.opensequences">{some_uuid}</property>
  <property name="kdenlive:docproperties.previewextension"/>
  <property name="kdenlive:docproperties.previewparameters"/>
  <property name="kdenlive:docproperties.profile">atsc_1080p_25</property>
  <property name="kdenlive:docproperties.proxyextension"/>
  <property name="kdenlive:docproperties.proxyimageminsize">2000</property>
  <property name="kdenlive:docproperties.proxyimagesize">800</property>
  <property name="kdenlive:docproperties.proxyminsize">1000</property>
  <property name="kdenlive:docproperties.proxyparams"/>
  <property name="kdenlive:docproperties.proxyresize">640</property>
  <property name="kdenlive:docproperties.seekOffset">15000</property>
  <property name="kdenlive:docproperties.sessionid">{another_uuid}</property>
  <property name="kdenlive:docproperties.uuid">{some_uuid}</property>
  <property name="kdenlive:docproperties.version">1.1</property>
  <property name="kdenlive:expandedFolders"/>
  <property name="kdenlive:binZoom">4</property>
  <property name="kdenlive:extraBins">project_bin:-1:0</property>
  <property name="kdenlive:documentnotes"/>
  <property name="kdenlive:documentnotesversion">2</property>
  <property name="xml_retain">1</property>
'''

# add the producers to the main_bin playlist
for i in producers.values():
  xml += f'<entry in="00:00:00.000" out="{i["duration"]}" producer="{i["producer_id"]}"/>\n'

xml += f'<entry in="00:00:00.000" out="{total_duration_time}" producer="tractor0"/>\n'
xml += '</playlist>\n'
# End of main_bin playlist
  
# =============================
# Playlist Audio
# =============================
#if music_file and music_file.exists():
#    xml += '\n  <playlist id="audio_track">\n'
#    xml += '    <entry producer="music"/>\n'
#    xml += '  </playlist>\n'

# =============================
# Tractor (with randomized transitions)
# =============================

# map logical transition names to services/ids (minimal mapping)
TRANSITION_MAP = {
    'mix': {'mlt_service': 'qtblend', 'kdenlive_id': 'qtblend'},
    'luma': {'mlt_service': 'composite', 'kdenlive_id': 'luma'},
    'wipe': {'mlt_service': 'composite', 'kdenlive_id': 'wipe'},
    'slide': {'mlt_service': 'composite', 'kdenlive_id': 'slide'},
    'composite': {'mlt_service': 'composite', 'kdenlive_id': 'composite'},
}

# build transitions between each adjacent image
transitions_xml = ''
trans_count = 0
for i in range(len(images) - 1):
    # transition spans the last `transition_frames` before the (i+1)-th image ends
    trans_end_frames = duration_frames * (i + 1)
    trans_start_frames = max(0, trans_end_frames - transition_frames)
    in_time = format_time_from_frames(trans_start_frames)
    out_time = format_time_from_frames(trans_end_frames)
    choice = random.choice(TRANSITIONS)
    mapping = TRANSITION_MAP.get(choice, TRANSITION_MAP['mix'])
    svc = mapping['mlt_service']
    kid = mapping['kdenlive_id']
    transitions_xml += f"\n  <transition id=\"transition{trans_count}\" in=\"{in_time}\" out=\"{out_time}\">\n"
    transitions_xml += "   <property name=\"a_track\">0</property>\n"
    transitions_xml += "   <property name=\"b_track\">1</property>\n"
    transitions_xml += "   <property name=\"compositing\">0</property>\n"
    transitions_xml += "   <property name=\"distort\">0</property>\n"
    transitions_xml += "   <property name=\"rotate_center\">0</property>\n"
    transitions_xml += f"   <property name=\"mlt_service\">{svc}</property>\n"
    transitions_xml += f"   <property name=\"kdenlive_id\">{kid}</property>\n"
    transitions_xml += "   <property name=\"internal_added\">237</property>\n"
    transitions_xml += "   <property name=\"always_active\">1</property>\n"
    transitions_xml += "  </transition>\n"
    trans_count += 1

xml += f'''\
<tractor id="tractor0" in="00:00:00.000" out="{total_duration_time}">\n  <property name="kdenlive:audio_track">1</property>\n  <property name="kdenlive:trackheight">72</property>\n  <property name="kdenlive:timeline_active">1</property>\n  <property name="kdenlive:collapsed">0</property>\n  <property name="kdenlive:thumbs_format"/>\n  <property name="kdenlive:audio_rec"/>\n  <track hide="audio" producer="playlist0"/>\n  <track hide="audio" producer="playlist1"/>\n'''

xml += transitions_xml

xml += f'  <property name="kdenlive:id">{kdenliveid}</property>\n</tractor>\n\n</mlt>\n'

# =============================
# Write to File
# =============================
current_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"slideshow_with_music_{image_folder.name}_{current_timestamp}.kdenlive"

with open(output_file, "w", encoding="utf-8") as f:
    f.write(xml)

print(f"Projektdatei erstellt: {output_file}")

csv_file = f"slideshow_{image_folder.name}_{current_timestamp}.csv"
with open(csv_file, "w", encoding="utf-8") as f:
    f.write("image_path,duration in seconds,overlapping\n")
    for image in images:
        f.write(f"{image},{duration_seconds},1\n")
        
print(f"CSV-Datei erstellt: {csv_file}")