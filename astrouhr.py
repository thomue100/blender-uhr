"""
Massive Messing-Zahnräder in Blender.

Erzeugt aus einer Liste von Zahnrad-Definitionen (Position, Radius, Drehachse,
Drehrichtung, Geschwindigkeit) massive, gefaste Messing-Zahnräder inklusive
Dauerrotation. Die Zähnezahl wird über ein einheitliches Modul skaliert,
damit alle Zahnräder geometrisch perfekt ineinandergreifen.

Ausführen: Blender -> Scripting-Tab -> dieses Skript laden -> Run Script
(oder headless: blender --background --python build_brass_gears.py)
"""

import json
import math
import os
import random

import bmesh
import bpy
import mathutils

# ============================================================
# KONFIGURATION - hier lässt sich das Ergebnis anpassen
# ============================================================

DEV_MODE_NO_TEETH = False  # True = Performance-Modus (nur glatte Zylinder), False = Volle Zähne

# Falls eine JSON-Datei mit demselben Schema neben diesem Skript liegt, wird
# sie automatisch geladen. Sonst greift die eingebettete GEAR_DATA weiter unten.
JSON_FILENAME = "projekt.json"

SCALE = 4.0  # Welt-Größenfaktor - macht aus den kleinen Radien "massive" Räder
GEAR_THICKNESS_RATIO = 0.35  # Dicke eines Rads relativ zu seinem Kopfkreis-Radius
TEETH_PER_UNIT_RADIUS = 10  # Automatische Zähnezahl (Radius * Faktor), da nicht vorgegeben
MIN_TEETH = 6  # Untergrenze, damit auch sehr kleine Räder noch wie Zahnräder aussehen
BEVEL_WIDTH = 0.025  # Kantenverrundung für den "poliert/gefertigt"-Look
BASE_ANGULAR_SPEED = math.radians(45)  # Grad/Sekunde bei speed = 1.0
CYCLE_FRAMES = 250  # Über diese Framespanne läuft die (endlos fortgesetzte) Animation
GEAR_MODULE = 0.45  # Fester Modulwert für alle Zahnräder – garantiert perfektes Ineinandergreifen!
COLLECTION_NAME = "Messingzahnraeder"
MATERIAL_NAME = "Messing"
STEEL_MATERIAL_NAME = "Stahl_Zahnraeder"
AXLE_STEEL_MATERIAL_NAME = "Stahl_Achsen"
AXIS_MATERIAL_NAME = "Transparente_Hohlachse"

# --- Echte Evolventenverzahnung (statt grobem Trapez-Platzhalter) ---
# Damit greifen die Zähne geometrisch tatsächlich korrekt ineinander:
# Der Wälzkreis (r_pitch) zweier kämmender Räder berührt sich exakt (Mittenabstand =
# Summe der Wälzkreisradien), der Zahnkopf (r_addendum) reicht dabei in den Zahnfuß
# (r_dedendum) des Gegenrads hinein, ohne diesen zu berühren (Kopfspiel).
PRESSURE_ANGLE = math.radians(20.0)  # Standard-Eingriffswinkel im Maschinenbau
ADDENDUM_COEFF = 1.0  # Zahnkopfhöhe = 1.0 * Modul
DEDENDUM_COEFF = 1.25  # Zahnfußhöhe = 1.25 * Modul (0.25*Modul Kopfspiel)
INVOLUTE_SEGMENTS = 6  # Stützpunkte pro Zahnflanke (Glätte der Evolvente)

# --- Zifferblatt + Sonnenzeiger (Lübecker-Uhr-Stil) ---
# Falls diese Bilddatei neben dem Skript liegt, wird sie als Zifferblatt-Textur
# verwendet; sonst wird ersatzweise ein einfarbiges dunkelblaues Zifferblatt erzeugt.
DIAL_IMAGE_FILENAME = "zifferring.png"
DIAL_MATERIAL_NAME = "Zifferblatt_Material"

# Drehrichtung/-geschwindigkeit der Hohlwelle, auf der Rad 6 (+ Rad 5) sitzen.
# Der Sonnenzeiger wird bewusst über dieselben Konstanten angetrieben, damit er
# IMMER exakt synchron zu dieser Achse läuft, auch wenn die Werte später geändert werden.
SHAFT_56_DIR = -1
SHAFT_56_SPEED = 1

# Drehrichtung/-geschwindigkeit der (eigenen, massiven) Welle von Rad 10 - der
# Mondzeiger wird bewusst über dieselben Konstanten angetrieben, damit er IMMER
# exakt synchron zu diesem (hintersten) Rad läuft.
SHAFT_10_DIR = -1
# WICHTIG: bewusst ungleich SHAFT_56_SPEED gewählt. Die Mondphase entsteht aus der
# DIFFERENZ zwischen der Mondzeiger-Wellendrehzahl (hier) und der Sonnenzeiger-
# Wellendrehzahl (SHAFT_56_SPEED) - sind beide gleich, gäbe es keine sichtbare
# Planetenbewegung (siehe build_moon_capsule_object).
SHAFT_10_SPEED = 1.6

MOON_MATERIAL_NAME = "Mondkugel_Schwarzlack"

# --- Planetengetriebe an der Mondzeiger-Spitze (siehe "Getriebe.jpg") ---
# Kleines, separates Modul für die beiden filigranen 24-zähnigen Getrieberäder
# (Zentralrad auf der Sonnenzeiger-Welle + Rad auf der Mondkugelwelle) - viel
# kleiner als GEAR_MODULE, da diese Räder nur Dekoration/Detail sind, nicht Teil
# der tragenden Hauptgetriebe-Kette.
MOON_GEAR_MODULE = 0.075
MOON_GEAR_TEETH = 24  # historisch: an der Stralsunder Nikolaikirche je 24 Zähne

# --- Sternscheibe (Astrolabium) mit "schwerkraftgefuehrten" Tierkreisfiguren ---
# Die Scheibe selbst dreht sich einmal pro (siderischem) Tag; die goldenen
# Tierkreis-Figuren darauf sind NICHT starr mit ihr verbunden, sondern per
# Gegengewicht drehbar gelagert, sodass sie durch die Schwerkraft immer
# aufrecht bleiben (siehe build_zodiac_figure_object fuer die Umsetzung).
STAR_DISC_DIR = -1
STAR_DISC_SPEED = 0.3  # deutlich langsamer als die "aktiven" Zeiger, gut sichtbar
STAR_DISC_MATERIAL_NAME = "Sternscheibe_Blau"

# Ordnet den JSON-Feldwert "axis" auf eine statische Vorab-Rotation ab, damit
# die lokale Z-Achse (= Extrusionsrichtung der Zahnrad-Silhouette) danach in
# die gewünschte Welt-Achse zeigt. Die eigentliche Dreh-Animation läuft dann
# immer um die lokale Z-Achse (siehe animate_spin).
AXIS_ALIGN_EULER = {
    "x": (0.0, math.radians(90.0), 0.0),
    "y": (math.radians(-90.0), 0.0, 0.0),
    "z": (0.0, 0.0, 0.0),
}

# Eingebettete Fallback-Daten (Inhalt der hochgeladenen projekt.json), falls
# keine externe Datei gefunden wird.
GEAR_DATA = [
    # --- Zentraler "Turm" (koaxial: 10 -> 7 -> 6/5 -> 2, alle bei x=0,y=0) ---
    # Rad 10: sitzt auf der innersten, massiven Welle (eigene Welle).
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 0, "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED, "axis": "z",
     "id": 10, "teeth": 64, "thickness": 0.25, "spoked": True},
    # Rad 7: eigenständige, einfache Welle (nicht Teil der Hohlwellen-Verschachtelung), kämmt mit 8.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 1, "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED, "axis": "z",
     "id": 7, "teeth": 64, "thickness": 0.25, "spoked": True},
    # Rad 6 + Rad 5: gemeinsame Hohlwelle, die die Welle von Rad 10 umhüllt.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 2, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 6, "teeth": 80, "thickness": 0.25, "spoked": True},
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 3, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 5, "teeth": 80, "thickness": 0.25, "spoked": True},
    # Rad 2: eigene (weitere/äußere) Hohlwelle, umhüllt die Hohlwelle von 6/5.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": 4, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED, "axis": "z",
     "id": 2, "teeth": 80, "thickness": 0.25, "spoked": True},

    # --- Parallelwelle A: 9 (kämmt mit 10) + 8 (gemeinsame Welle mit 9, kämmt mit 7) ---
    # y-Abstand = (r_pitch(16) + r_pitch(64)) / SCALE = (3.6 + 14.4) / 4 = 4.5
    {"type": "gear", "group": None, "x": 0, "y": -4.5, "z": 0, "dir": -SHAFT_10_DIR, "speed": SHAFT_10_SPEED * 4,
     "axis": "z", "id": 9, "teeth": 16, "thickness": 0.25},
    {"type": "gear", "group": None, "x": 0, "y": -4.5, "z": 1, "dir": -SHAFT_10_DIR, "speed": SHAFT_10_SPEED * 4,
     "axis": "z", "id": 8, "teeth": 16, "thickness": 0.25},

    # --- Parallelwelle B: 4 (kämmt mit 5) + 3 (gemeinsame Welle mit 4, kämmt mit 2) ---
    # y-Abstand = (r_pitch(16) + r_pitch(80)) / SCALE = (3.6 + 18.0) / 4 = 5.4
    {"type": "gear", "group": None, "x": 0, "y": -5.4, "z": 3, "dir": -SHAFT_56_DIR, "speed": SHAFT_56_SPEED * 5,
     "axis": "z", "id": 4, "teeth": 16, "thickness": 0.25},
    {"type": "gear", "group": None, "x": 0, "y": -5.4, "z": 4, "dir": -SHAFT_56_DIR, "speed": SHAFT_56_SPEED * 5,
     "axis": "z", "id": 3, "teeth": 16, "thickness": 0.25},

    # --- Sichtbare (teil-transparente) Hohlwellen-Objekte fuer den zentralen Turm ---
    # Innerste, massive Welle von Rad 10.
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.15, "hollow": False, "id": "10"},
    # Hohlwelle, die die Welle von Rad 10 umhuellt; traegt Rad 6 + 5.
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.35, "wall_thickness": 0.15, "hollow": True,
     "id": "56"},

    # Kleines Abtriebs-/Antriebs-Zahnrad (15 Zaehne) auf der 56-Welle (dieselbe
    # Welle wie Rad 5+6) - sitzt am hinteren Ende dieser Welle, "nach hinten
    # raus" (gegenueber vom Zifferblatt), ein Stueck hinter Rad 10 (dem
    # hintersten Hauptrad). Bleibt massiv (kein "spoked"), da klein.
    {"type": "gear", "group": None, "x": 0, "y": 0, "z": -0.3, "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED,
     "axis": "z", "id": "abtrieb56", "teeth": 15, "thickness": 0.25},
    # Aeussere Hohlwelle darueber, umhuellt die Welle von 6/5; traegt Rad 2.
    {"type": "axis", "x": 0, "y": 0, "z": -0.4, "length": 4.8, "r": 0.60, "wall_thickness": 0.20, "hollow": True,
     "id": "2"},

    # --- Zifferblatt + Sonnenzeiger (verdeckt das Räderwerk, wie bei einer echten Uhr) ---
    # Zifferblatt: ruht knapp über Rad 2 (Kopfkreis ~18.45), deckt den ganzen Turm ab.
    {"type": "dial", "id": "zifferblatt", "x": 0, "y": 0, "z": 4.375, "radius": 19.0},
    # Sonnenzeiger: sitzt sichtbar auf dem Zifferblatt, wird aber bewusst über
    # SHAFT_56_DIR/SPEED angetrieben - exakt dieselbe Achse wie Rad 6 (+5).
    {"type": "hand", "id": "sonnenzeiger", "x": 0, "y": 0, "z": 4.5, "axis": "z",
     "dir": SHAFT_56_DIR, "speed": SHAFT_56_SPEED,
     "length": 15.35, "sun_radius": 1.1, "rays": 24, "thickness": 0.4},

    # Mondzeiger: duennes Rohr + zweifarbige (halb gold/halb schwarz) Kugel in
    # schwarzer Metall-Halbkugelfassung. Angetrieben von der eigenen Welle von
    # Rad 10 (dem hintersten Rad, urspruenglich 347 Zaehne).
    {"type": "moon_hand", "id": "mondzeiger", "x": 0, "y": 0, "z": 4.55, "axis": "z",
     "dir": SHAFT_10_DIR, "speed": SHAFT_10_SPEED,
     "length": 14.5, "ball_radius": 1.1, "rod_thickness": 0.35},

    # Kleines, sichtbares "Zentralrad" auf der Sonnenzeiger-Welle wurde wieder
    # entfernt (nicht originalgetreu genug).

    # Sichtbare gemeinsame Achse fuer Radpaar 3+4 ("vordere Gruppe", dem
    # Zifferblatt zugewandt, z=3..4) - nur die Achse selbst, keine Platine/
    # Strebe/Bodenplatte.
    {"type": "axis", "id": "3_4", "x": 0, "y": -5.4, "z": 2.9, "length": 1.5,
     "r": 0.075, "hollow": False, "steel": True},

    # Sichtbare gemeinsame Achse fuer Radpaar 8+9 ("hintere Gruppe", z=0..1).
    {"type": "axis", "id": "8_9", "x": 0, "y": -4.5, "z": -0.1, "length": 1.5,
     "r": 0.075, "hollow": False, "steel": True},

    # --- Sternscheibe: sitzt knapp unter dem Zifferblatt (zwischen Zifferblatt
    # und den Haupt-Zahnraedern), Radius etwas kleiner als das Zifferblatt,
    # damit der aeussere Ring mit den roemischen Ziffern sichtbar bleibt.
    {"type": "star_disc", "id": "sternscheibe", "x": 0, "y": 0, "z": 4.40,
     "radius": 15.35, "image": "sternhimmel.png"},

    # Alle 13 Tierkreiszeichen der Luebecker Uhr (inkl. Schlangentraeger
    # zwischen Skorpion und Schuetze, wie am echten Sternbild-Pfad), gleich-
    # maessig verteilt (360/13 Grad). Jede Figur nutzt das mitgelieferte PNG
    # als Textur (keine eigene Modellierung noetig) und ist ein Kind der
    # Sternscheibe mit automatischer Gegenrotation.
    {"type": "zodiac_figure", "id": "widder", "parent_id": "sternscheibe",
     "angle_deg": 225.00, "orbit_radius": 10.09, "image": "widder.png"},
    {"type": "zodiac_figure", "id": "stier", "parent_id": "sternscheibe",
     "angle_deg": 240.00, "orbit_radius": 10.09, "image": "stier.png"},
    {"type": "zodiac_figure", "id": "zwilling", "parent_id": "sternscheibe",
     "angle_deg": 270.00, "orbit_radius": 10.09, "image": "zwilling.png"},
    {"type": "zodiac_figure", "id": "krebs", "parent_id": "sternscheibe",
     "angle_deg": 300.00, "orbit_radius": 10.09, "image": "krebs.png"},
    {"type": "zodiac_figure", "id": "loewe", "parent_id": "sternscheibe",
     "angle_deg": 330.00, "orbit_radius": 10.09, "image": "loewe.png"},
    {"type": "zodiac_figure", "id": "jungfrau", "parent_id": "sternscheibe",
     "angle_deg": 7.50, "orbit_radius": 10.09, "image": "jungfrau.png"},
    {"type": "zodiac_figure", "id": "waage", "parent_id": "sternscheibe",
     "angle_deg": 30.00, "orbit_radius": 10.09, "image": "waage.png"},
    {"type": "zodiac_figure", "id": "skorpion", "parent_id": "sternscheibe",
     "angle_deg": 285.00, "orbit_radius": 10.09, "image": "skorpion.png"},
    {"type": "zodiac_figure", "id": "schlangentraeger", "parent_id": "sternscheibe",
     "angle_deg": 60.00, "orbit_radius": 10.09, "image": "schlangentraeger.png"},
    {"type": "zodiac_figure", "id": "schuetze", "parent_id": "sternscheibe",
     "angle_deg": 90.00, "orbit_radius": 10.09, "image": "schuetze.png"},
    {"type": "zodiac_figure", "id": "steinbock", "parent_id": "sternscheibe",
     "angle_deg": 120.00, "orbit_radius": 10.09, "image": "steinbock.png"},
    {"type": "zodiac_figure", "id": "wassermann", "parent_id": "sternscheibe",
     "angle_deg": 150.00, "orbit_radius": 10.09, "image": "wassermann.png"},
    {"type": "zodiac_figure", "id": "fische", "parent_id": "sternscheibe",
     "angle_deg": 195.00, "orbit_radius": 10.09, "image": "fische.png"},

    # Zentrales "Heiland"-Medaillon (Christus mit Erdkugel, Strahlenkranz) -
    # sitzt exakt im Zentrum der Sternscheibe (orbit_radius=0). Nutzt dieselbe
    # Gegenrotations-Mechanik wie die Tierkreisfiguren, damit es unabhaengig
    # von der Scheibendrehung nie "mitdreht", sondern fest ausgerichtet bleibt
    # (wie im Original).
    {"type": "zodiac_figure", "id": "heiland", "parent_id": "sternscheibe",
     "angle_deg": 0.0, "orbit_radius": 0.0, "image": "heiland.png", "height": 6.14},
]


# ============================================================
# HILFSFUNKTIONEN
# ============================================================

def load_gear_data():
    """Lädt die Zahnrad-Konfiguration aus einer JSON-Datei neben dem Skript,
    fällt sonst auf die eingebettete GEAR_DATA zurück."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    json_path = os.path.join(script_dir, JSON_FILENAME)
    if os.path.isfile(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return GEAR_DATA


def get_or_create_collection(name):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def clear_collection(collection):
    """Entfernt nur zuvor von diesem Skript erzeugte Objekte, lässt die restliche Szene unangetastet."""
    for obj in list(collection.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def get_or_create_brass_material():
    if MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MATERIAL_NAME]

    mat = bpy.data.materials.new(MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.72, 0.52, 0.18, 1.0)
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.32
        if "Specular IOR Level" in bsdf.inputs:  # Blender 4.x Benennung
            bsdf.inputs["Specular IOR Level"].default_value = 0.6
    return mat


def get_or_create_steel_material():
    """Stahlgraues Material für die Zahnräder des Getriebes (wie auf dem
    Originalfoto - die eigentlichen Räder sind Stahl/Gusseisen, nicht golden;
    golden bleiben nur die sichtbaren Zifferblatt-Elemente wie Zeiger und
    Sternscheiben-Zierrat)."""
    if STEEL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[STEEL_MATERIAL_NAME]

    mat = bpy.data.materials.new(STEEL_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.43, 0.45, 1.0)  # stahlgrau
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.45  # etwas matter als poliertes Messing
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.5
    return mat


def get_or_create_moon_material():
    """Schwarz lackiertes Material für die verborgene Hälfte der Mondphasenkugel
    - glänzender Lack, kein Metallic, im Kontrast zur goldfarben polierten
    sichtbaren Hälfte."""
    if MOON_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[MOON_MATERIAL_NAME]

    mat = bpy.data.materials.new(MOON_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.008, 0.008, 0.01, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.15  # glänzender Lack
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.6
    return mat


def get_or_create_transparent_material():
    if AXIS_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[AXIS_MATERIAL_NAME]

    mat = bpy.data.materials.new(AXIS_MATERIAL_NAME)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'  # Aktiviert Transparenz in Eevee/Cycles
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.9, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.8
        bsdf.inputs["Roughness"].default_value = 0.2
        bsdf.inputs["Alpha"].default_value = 0.35  # Transparenz-Grad (0 = unsichtbar, 1 = opak)
    return mat


def find_image_path(filename):
    """Sucht eine Bilddatei an mehreren plausiblen Orten, weil je nach
    Aufruf-Art (gespeicherte .py-Datei, Blender-Text-Editor, headless) unterschiedliche
    Ordner als "Skript-Ordner" gelten. Wird sowohl für das Zifferblatt als auch
    für alle Tierkreiszeichen-Bilder verwendet."""
    candidates = []
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    if bpy.data.filepath:
        candidates.append(os.path.dirname(bpy.data.filepath))  # Ordner der .blend-Datei
    candidates.append(os.getcwd())

    for folder in candidates:
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            return path, candidates
    return None, candidates


def find_dial_image_path():
    return find_image_path(DIAL_IMAGE_FILENAME)


_figure_material_cache = {}  # Dateiname -> (Material, Image-Breite/Höhe oder None)


def get_or_create_figure_material(image_filename):
    """Lädt ein Tierkreiszeichen-Bild (mit Transparenz) als Material - eine
    Kachel pro Bilddatei, gecacht. Gibt (material, aspect_ratio) zurück, wobei
    aspect_ratio = Bildbreite/Bildhöhe ist (für die passende Seitenverhältnis-
    Berechnung der Bild-Ebene); aspect_ratio=1.0 als Fallback, falls das Bild
    nicht gefunden wird (dann einfarbiges Gold-Ersatzmaterial)."""
    if image_filename in _figure_material_cache:
        return _figure_material_cache[image_filename]

    material_name = f"Tierkreiszeichen_{os.path.splitext(image_filename)[0]}"
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    # WICHTIG: 'CLIP' statt 'BLEND' - BLEND-Transparenz wird in Eevee pro Objekt
    # sortiert (nicht pro Pixel) und kann dadurch, je nach Blickwinkel/Position
    # relativ zu anderen halbtransparenten Flaechen (z.B. der Sternscheibe
    # dahinter), als dunkles/schwarzes Rechteck aufblitzen, bis die Sortierung
    # "aufgeloest" ist (z.B. wenn die Figur weit genug im Vordergrund ist).
    # Da unsere PNGs ohnehin harte Kanten haben (voll deckend oder komplett
    # transparent, keine weichen Verlaeufe), behebt CLIP das Problem sauber:
    # es schreibt pixelgenau in den Tiefenpuffer, keine Sortierprobleme mehr.
    mat.blend_method = 'CLIP'
    mat.alpha_threshold = 0.5
    mat.show_transparent_back = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    image_path, searched_folders = find_image_path(image_filename)
    aspect_ratio = 1.0

    if image_path is not None:
        image = bpy.data.images.get(image_filename)
        if image is None:
            image = bpy.data.images.load(image_path)
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-300, 300)
        tex_node.image = image
        if bsdf is not None:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
            bsdf.inputs["Roughness"].default_value = 0.35
            bsdf.inputs["Metallic"].default_value = 0.6  # golden schimmernd, wie im Original
        w, h = image.size
        if h > 0:
            aspect_ratio = w / h
        print(f"[Tierkreiszeichen] '{image_filename}' geladen (Seitenverhältnis {aspect_ratio:.3f}).")
    else:
        print(f"[Tierkreiszeichen] WARNUNG: '{image_filename}' nicht gefunden in {searched_folders} "
              f"- verwende einfarbiges Gold-Ersatzmaterial.")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.83, 0.68, 0.21, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.6
            bsdf.inputs["Roughness"].default_value = 0.35

    _figure_material_cache[image_filename] = (mat, aspect_ratio)
    return mat, aspect_ratio


def get_or_create_dial_material():
    """Zifferblatt-Material: lädt das mitgelieferte Bild als Textur (Base Color).
    Liegt die Datei nicht neben dem Skript, wird ersatzweise ein einfarbiges,
    dunkelblaues Zifferblatt-Material erzeugt (kein Absturz)."""
    if DIAL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[DIAL_MATERIAL_NAME]

    mat = bpy.data.materials.new(DIAL_MATERIAL_NAME)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    image_path, searched_folders = find_dial_image_path()

    if image_path is not None:
        image = bpy.data.images.get(DIAL_IMAGE_FILENAME)
        if image is None:
            image = bpy.data.images.load(image_path)
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-300, 300)
        tex_node.image = image
        if bsdf is not None:
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            bsdf.inputs["Roughness"].default_value = 0.45
            bsdf.inputs["Metallic"].default_value = 0.0
        print(f"[Zifferblatt] Bild gefunden und geladen: {image_path}")
    else:
        msg = (f"'{DIAL_IMAGE_FILENAME}' wurde in keinem dieser Ordner gefunden: "
               f"{searched_folders} - verwende einfarbiges Ersatz-Zifferblatt. Bitte die "
               f"Bilddatei in einen dieser Ordner legen (am einfachsten: selben Ordner wie "
               f"die gespeicherte .blend-Datei) und das Skript erneut ausführen.")
        print(f"[Zifferblatt] WARNUNG: {msg}")

        # Zusätzlich als gut sichtbares Popup in Blender selbst (nicht nur Konsole):
        def _draw_warning(self, context):
            self.layout.label(text=f"Zifferblatt-Bild nicht gefunden: {DIAL_IMAGE_FILENAME}")
            self.layout.label(text="Ersatzmaterial (einfarbig) wird verwendet.")

        try:
            bpy.context.window_manager.popup_menu(_draw_warning, title="Zifferblatt-Warnung", icon='ERROR')
        except Exception:
            pass  # Popup ist nur ein Komfort-Extra, kein kritischer Schritt
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.06, 0.09, 0.17, 1.0)  # dunkelblau, wie im Referenzbild
            bsdf.inputs["Roughness"].default_value = 0.5
            bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def compute_teeth_count(outer_radius):
    return max(MIN_TEETH, round(outer_radius * TEETH_PER_UNIT_RADIUS))


def compute_gear_radii(module, teeth):
    """Liefert die vier für die Evolventenverzahnung nötigen Kreisradien.
    r_pitch (Wälzkreis) bestimmt den korrekten Mittenabstand kämmender Räder;
    r_addendum (Kopfkreis) ist der tatsächliche Außenradius des Rads."""
    r_pitch = module * teeth / 2.0
    r_base = r_pitch * math.cos(PRESSURE_ANGLE)
    r_addendum = r_pitch + ADDENDUM_COEFF * module
    r_dedendum = r_pitch - DEDENDUM_COEFF * module
    return r_pitch, r_base, r_addendum, r_dedendum


def _involute_angle(r_base, r):
    """Evolventenfunktion inv(alpha) = tan(alpha) - alpha für Radius r (>= r_base)
    auf einer Evolvente, die am Grundkreis r_base beginnt."""
    r = max(r, r_base)
    alpha = math.acos(r_base / r)
    return math.tan(alpha) - alpha


def build_involute_profile(module, teeth, segments=INVOLUTE_SEGMENTS):
    """Erzeugt die vollständige, geschlossene Außenkontur eines Zahnrads mit echter
    Evolventenverzahnung als Liste von (x, y)-Punkten (ein Umlauf, alle Zähne)."""
    r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(module, teeth)

    # Winkel-Halbbreite eines Zahns am Wälzkreis (Standard, ohne Profilverschiebung):
    # Zahndicke am Wälzkreis = halbe Zahnteilung (pi*modul/2).
    half_tooth_angle = math.pi / (2.0 * teeth)
    inv_at_pitch = _involute_angle(r_base, r_pitch)
    theta_ref = half_tooth_angle + inv_at_pitch

    # Start der Evolvente: normalerweise am Fußkreis; liegt dieser (bei wenigen Zähnen)
    # innerhalb des Grundkreises, beginnt die Evolvente am Grundkreis und ein kurzes
    # radiales Stück bildet den (vereinfachten) Unterschnitt-Übergang zum Fußkreis.
    flank_start_r = max(r_dedendum, r_base)

    # Evolvente von flank_start_r (Fuß- oder Grundkreis) bis zum Kopfkreis,
    # mit aufsteigendem Radius (root -> tip).
    flank_root_to_tip = []
    for i in range(segments + 1):
        t = i / segments
        r = flank_start_r + t * (r_addendum - flank_start_r)
        theta = theta_ref - _involute_angle(r_base, r)
        flank_root_to_tip.append((theta, r))

    needs_root_transition = flank_start_r > r_dedendum + 1e-9
    theta_at_flank_start = flank_root_to_tip[0][0]

    tooth_step = 2.0 * math.pi / teeth
    points = []
    for i in range(teeth):
        offset = i * tooth_step
        # 1) Optionaler Übergang vom Fußkreis zum Grundkreis (linke Seite),
        #    nur bei sehr wenigen Zähnen nötig (Unterschnitt-Fall).
        if needs_root_transition:
            points.append((-theta_at_flank_start + offset, r_dedendum))
        # 2) Linke Flanke: root -> tip
        points.extend((-theta + offset, r) for theta, r in flank_root_to_tip)
        # 3) Rechte Flanke: tip -> root (gespiegelt & umgekehrte Reihenfolge)
        points.extend((theta + offset, r) for theta, r in reversed(flank_root_to_tip))
        # 4) Optionaler Übergang zurück zum Fußkreis (rechte Seite)
        if needs_root_transition:
            points.append((theta_at_flank_start + offset, r_dedendum))
        # Die Zahnlücke zum nächsten Zahn ergibt sich automatisch: der nächste
        # Punkt (nächster Schleifendurchlauf) liegt bei -theta_at_flank_start
        # + offset + tooth_step, wieder auf dem Fußkreis -> flache Lückensohle.

    return [(r * math.cos(theta), r * math.sin(theta)) for theta, r in points], r_addendum


def add_spoked_gear_profile(bm, profile_xy, hub_radius, rim_inner_radius, spoke_width,
                            num_spokes=6, hub_segments=32):
    """Baut das 2D-Profil eines Speichenrads: massiver Zahnkranz (Ring zwischen
    Kopfkreis-Kontur und Innenradius), massive Nabe in der Mitte, und dazwischen
    `num_spokes` gleich dicke, NICHT verjüngende Speichen (parallele Kanten,
    wie im Original-Foto - keine Trapezform). Zwischen den Speichen bleibt die
    Fläche bewusst offen (Fenster), wie bei einem echten Speichenrad."""
    # 1) Zahnkranz: Ring zwischen der Kopfkreis-Kontur (aussen) und einem
    #    Innenkreis (innen) - Innenpunkte liegen jeweils auf demselben Winkel
    #    wie die Aussenkontur, nur mit kleinerem Radius.
    outer_verts = [bm.verts.new((x, y, 0.0)) for x, y in profile_xy]
    inner_verts = []
    for x, y in profile_xy:
        theta = math.atan2(y, x)
        inner_verts.append(bm.verts.new((rim_inner_radius * math.cos(theta),
                                         rim_inner_radius * math.sin(theta), 0.0)))
    n = len(profile_xy)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((outer_verts[i], outer_verts[j], inner_verts[j], inner_verts[i]))

    # 2) Nabe: massive Scheibe in der Mitte (für die Achse).
    hub_verts = [
        bm.verts.new((hub_radius * math.cos(2.0 * math.pi * i / hub_segments),
                      hub_radius * math.sin(2.0 * math.pi * i / hub_segments), 0.0))
        for i in range(hub_segments)
    ]
    bm.faces.new(hub_verts)

    # 3) Speichen: gerade, gleich dicke Baelken (parallele Kanten im Abstand
    #    +/- halbe Speichenbreite von der radialen Mittelachse - dadurch KEINE
    #    Verjuengung nach aussen, anders als eine einfache Trapez-Speiche).
    half_w = spoke_width * 0.5
    for i in range(num_spokes):
        theta = 2.0 * math.pi * i / num_spokes
        dx, dy = math.cos(theta), math.sin(theta)
        px, py = -math.sin(theta), math.cos(theta)
        t_inner = math.sqrt(max(hub_radius ** 2 - half_w ** 2, 0.0))
        t_outer = math.sqrt(max(rim_inner_radius ** 2 - half_w ** 2, 0.0))

        def spoke_point(t, s):
            return (t * dx + s * px, t * dy + s * py, 0.0)

        v_il = bm.verts.new(spoke_point(t_inner, -half_w))
        v_ol = bm.verts.new(spoke_point(t_outer, -half_w))
        v_or = bm.verts.new(spoke_point(t_outer, half_w))
        v_ir = bm.verts.new(spoke_point(t_inner, half_w))
        bm.faces.new((v_il, v_ol, v_or, v_ir))


def build_gear_mesh(name, module, teeth, thickness, outer_radius_dev=None, spoked=False,
                    num_spokes=6, hub_radius_ratio=0.22, rim_inner_ratio=0.915,
                    spoke_width_ratio=0.08):
    """Baut ein Zahnrad mit echter Evolventenverzahnung, oder im Dev-Modus einen
    simplen glatten Zylinder (Performance-Vorschau ohne Zähne). Mit spoked=True
    entsteht ein Speichenrad (6 gleich dicke Speichen, wie im Original-Foto der
    Uhr) statt einer massiven Scheibe - passend für die groesseren Zahnraeder;
    kleinere Zahnraeder bleiben mit spoked=False massiv."""
    bm = bmesh.new()

    if DEV_MODE_NO_TEETH:
        # Dev-Modus: Einfacher Kreis als N-Gon für maximale Performance
        radius = outer_radius_dev if outer_radius_dev is not None else compute_gear_radii(module, teeth)[2]
        segments = 32  # Glattheit des Ersatz-Zylinders
        profile_verts = []
        for i in range(segments):
            angle = i * (2.0 * math.pi / segments)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            profile_verts.append(bm.verts.new((x, y, 0.0)))

        bm.verts.ensure_lookup_table()
        bm.faces.new(profile_verts)
    else:
        # Normaler Modus: echte Evolventenkontur mit der tatsächlichen Zähnezahl,
        # damit die Zahnteilung exakt zum berechneten Mittenabstand passt.
        profile_xy, _ = build_involute_profile(module, teeth)

        if spoked:
            r_pitch, _r_base, _r_add, _r_ded = compute_gear_radii(module, teeth)
            hub_radius = r_pitch * hub_radius_ratio
            rim_inner_radius = r_pitch * rim_inner_ratio
            spoke_width = r_pitch * spoke_width_ratio
            add_spoked_gear_profile(bm, profile_xy, hub_radius, rim_inner_radius,
                                    spoke_width, num_spokes=num_spokes)
        else:
            profile_verts = [bm.verts.new((x, y, 0.0)) for x, y in profile_xy]
            bm.verts.ensure_lookup_table()
            bm.faces.new(profile_verts)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Entlang der lokalen Z-Achse extrudieren, um die Dicke zu erzeugen (alle
    # bisherigen 2D-Flaechen gemeinsam - egal ob 1 massive Flaeche oder viele
    # einzelne Speichenrad-Flaechen).
    all_faces = list(bm.faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=all_faces)
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_axis_mesh(name, radius, length, hollow=False, wall_thickness=0.05):
    bm = bmesh.new()
    segments = 32

    # Äußerer Zylinder
    outer_verts = []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        outer_verts.append(bm.verts.new((x, y, 0.0)))

    bm.verts.ensure_lookup_table()
    outer_face = bm.faces.new(outer_verts)

    if hollow:
        # Innerer Zylinder für die Hohlachse (Gegenläufige Face-Normalen oder Deckel-Verbindung)
        inner_radius = max(0.01, radius - wall_thickness)
        inner_verts = []
        for i in range(segments - 1, -1, -1):  # Umgekehrte Reihenfolge für korrekte Normale innen
            angle = i * (2.0 * math.pi / segments)
            x = inner_radius * math.cos(angle)
            y = inner_radius * math.sin(angle)
            inner_verts.append(bm.verts.new((x, y, 0.0)))

        bm.verts.ensure_lookup_table()
        # Wir löschen das geschlossene N-Gon und extrudieren stattdessen einen Ring
        bm.faces.remove(outer_face)
        ring_verts = outer_verts[::-1] + inner_verts
        base_face = bm.faces.new(ring_verts)

        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[base_face])
    else:
        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[outer_face])

    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, length))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def get_or_create_axle_steel_material():
    """Zweite Stahl-Variante speziell für einzelne Achsen (z.B. 3_4/8_9) - etwas
    dunkler/kühler als das Zahnrad-Stahl, damit sich Achse und Räder optisch
    leicht unterscheiden, aber erkennbar zur selben Materialfamilie gehören."""
    if AXLE_STEEL_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[AXLE_STEEL_MATERIAL_NAME]

    mat = bpy.data.materials.new(AXLE_STEEL_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.30, 0.32, 0.36, 1.0)  # dunkler, kuehleres Stahlblau-Grau
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.30  # etwas glaenzender (poliertes Achsenstahl)
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.55
    return mat


def build_axis_object(entry, collection, brass_material, transparent_material, axle_steel_material=None):
    radius = float(entry.get("r", 0.2)) * SCALE
    length = float(entry.get("length", 5.0)) * SCALE
    hollow = bool(entry.get("hollow", False))
    wall_thickness = float(entry.get("wall_thickness", 0.05)) * SCALE

    name = f"Achse_{entry.get('id', 'fix')}"
    mesh = build_axis_mesh(name, radius, length, hollow=hollow, wall_thickness=wall_thickness)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    # Material zuweisen: transparent bei Hohlachsen, sonst wahlweise die
    # (dunklere) Achsen-Stahlvariante (entry["steel"]=True) oder Messing/Standard.
    if hollow:
        mat = transparent_material
    elif bool(entry.get("steel", False)) and axle_steel_material is not None:
        mat = axle_steel_material
    else:
        mat = brass_material
    if mesh.materials:
        mesh.materials[0] = mat
    else:
        mesh.materials.append(mat)

    return obj


def get_or_create_star_disc_material():
    """Dunkelblaues Material fuer die Sternscheibe (Hintergrund der Tierkreis-
    figuren), passend zum Zifferblatt-Blauton."""
    if STAR_DISC_MATERIAL_NAME in bpy.data.materials:
        return bpy.data.materials[STAR_DISC_MATERIAL_NAME]
    mat = bpy.data.materials.new(STAR_DISC_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.03, 0.07, 0.22, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.4
    return mat


def build_dial_mesh(name, radius, segments=96):
    """Kreisrunde Scheibe mit einfacher planarer UV-Projektion (Bild füllt den
    Kreis randfüllend aus, passend zum mitgelieferten Zifferblatt-Bild)."""
    bm = bmesh.new()
    verts = []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts.append(bm.verts.new((x, y, 0.0)))

    face = bm.faces.new(verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    uv_layer = bm.loops.layers.uv.new()
    for loop in face.loops:
        vx, vy = loop.vert.co.x, loop.vert.co.y
        loop[uv_layer].uv = ((vx / radius + 1.0) / 2.0, (vy / radius + 1.0) / 2.0)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_dial_object(entry, collection, material):
    radius = float(entry.get("radius", 19.0))
    name = f"Zifferblatt_{entry.get('id', '?')}"
    mesh = build_dial_mesh(name, radius)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    return obj


def add_rod_geometry(bm, radius, y_start, y_end, segments=16):
    """Fügt einen echten zylindrischen Stab entlang der lokalen Y-Achse zu einem
    bestehenden bmesh hinzu (von y_start bis y_end). Wird sowohl vom Sonnen- als
    auch vom Mondzeiger verwendet, damit beide optisch dasselbe dünne Rohr haben."""
    ring_back, ring_front = [], []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        cx = radius * math.cos(angle)
        cz = radius * math.sin(angle)
        ring_back.append(bm.verts.new((cx, y_start, cz)))
        ring_front.append(bm.verts.new((cx, y_end, cz)))
    bm.verts.ensure_lookup_table()
    for i in range(segments):
        j = (i + 1) % segments
        bm.faces.new((ring_back[i], ring_back[j], ring_front[j], ring_front[i]))
    bm.faces.new(list(reversed(ring_back)))  # Kappe hinten
    bm.faces.new(ring_front)  # Kappe vorne


def add_rod_along_z(bm, radius, z_start, z_end, segments=16, material_index=0,
                    x_offset=0.0, y_offset=0.0):
    """Wie add_rod_geometry, aber entlang der lokalen Z-Achse (vorne/hinten aus
    Kamerasicht) - für die gemeinsame Welle, die je zwei kleine Zahnräder
    verbindet. x_offset/y_offset verschieben die Welle an eine beliebige Stelle
    (z.B. an die Spitze des Zeigerarms)."""
    ring_back, ring_front = [], []
    for i in range(segments):
        angle = i * (2.0 * math.pi / segments)
        cx = radius * math.cos(angle) + x_offset
        cy = radius * math.sin(angle) + y_offset
        ring_back.append(bm.verts.new((cx, cy, z_start)))
        ring_front.append(bm.verts.new((cx, cy, z_end)))
    bm.verts.ensure_lookup_table()
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append(bm.faces.new((ring_back[i], ring_back[j], ring_front[j], ring_front[i])))
    faces.append(bm.faces.new(list(reversed(ring_back))))
    faces.append(bm.faces.new(ring_front))
    for f in faces:
        f.material_index = material_index


def add_box(bm, x_range, y_range, z_range, material_index=0):
    """Simpler Quader (für Streben und Bodenplatte)."""
    x0, x1 = x_range
    y0, y1 = y_range
    z0, z1 = z_range
    v = {}
    for xi in (x0, x1):
        for yi in (y0, y1):
            for zi in (z0, z1):
                v[(xi, yi, zi)] = bm.verts.new((xi, yi, zi))
    faces = [
        bm.faces.new((v[(x0, y0, z0)], v[(x0, y1, z0)], v[(x0, y1, z1)], v[(x0, y0, z1)])),
        bm.faces.new((v[(x1, y0, z0)], v[(x1, y0, z1)], v[(x1, y1, z1)], v[(x1, y1, z0)])),
        bm.faces.new((v[(x0, y0, z0)], v[(x0, y0, z1)], v[(x1, y0, z1)], v[(x1, y0, z0)])),
        bm.faces.new((v[(x0, y1, z0)], v[(x1, y1, z0)], v[(x1, y1, z1)], v[(x0, y1, z1)])),
        bm.faces.new((v[(x0, y0, z0)], v[(x1, y0, z0)], v[(x1, y1, z0)], v[(x0, y1, z0)])),
        bm.faces.new((v[(x0, y0, z1)], v[(x0, y1, z1)], v[(x1, y1, z1)], v[(x1, y0, z1)])),
    ]
    for f in faces:
        f.material_index = material_index


def add_disc_plate(bm, radius, z_center, thickness, material_index=0, segments=32,
                   x_offset=0.0, y_offset=0.0):
    """Flache, runde Scheibe ('Platine') senkrecht zur Z-Achse - die Wellen der
    Zahnräder laufen durch sie hindurch (rein visuell, keine echten Bohrungen)."""
    verts_bottom = [
        bm.verts.new((radius * math.cos(2 * math.pi * i / segments) + x_offset,
                      radius * math.sin(2 * math.pi * i / segments) + y_offset,
                      z_center - thickness * 0.5))
        for i in range(segments)
    ]
    face_bottom = bm.faces.new(verts_bottom)
    faces_before = set(bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=[face_bottom])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face_bottom])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = material_index
    face_bottom.material_index = material_index


def add_hemisphere_shell(bm, radius, thickness, center, segments=32, rings=16,
                         material_index=0, direction=1.0):
    """Hohle Halbkugel-Schale mit echter Wandstärke (Außen- und Innenfläche plus
    Rand) - Portierung der vom Nutzer bereitgestellten, funktionierenden
    create_bowl_hemisphere()-Logik in unser bmesh-System. direction=+1: Kuppel
    öffnet sich nach -Z (Rand bei center.z, Kuppelspitze bei center.z - radius);
    direction=-1: umgekehrt."""
    cx, cy, cz = center
    grid = {}
    for inner in (False, True):
        r = radius - thickness if inner else radius
        for j in range(rings + 1):
            theta = (math.pi / 2.0) * j / rings
            z = cz - direction * r * math.cos(theta)
            ring_r = r * math.sin(theta)
            for i in range(segments):
                phi = 2.0 * math.pi * i / segments
                x = ring_r * math.cos(phi) + cx
                y = ring_r * math.sin(phi) + cy
                grid[(inner, j, i)] = bm.verts.new((x, y, z))

    faces = []
    for inner in (False, True):
        for j in range(rings):
            for i in range(segments):
                i2 = (i + 1) % segments
                a, b = grid[(inner, j, i)], grid[(inner, j, i2)]
                c, d = grid[(inner, j + 1, i2)], grid[(inner, j + 1, i)]
                if inner:
                    faces.append(bm.faces.new((a, d, c, b)))
                else:
                    faces.append(bm.faces.new((a, b, c, d)))
    # Rand (Aequator-Ring) verbindet Aussen- und Innenflaeche
    for i in range(segments):
        i2 = (i + 1) % segments
        a, b = grid[(False, rings, i)], grid[(False, rings, i2)]
        c, d = grid[(True, rings, i2)], grid[(True, rings, i)]
        faces.append(bm.faces.new((a, d, c, b)))

    for f in faces:
        f.material_index = material_index


def build_sun_hand_mesh(name, length, sun_radius, rays, thickness,
                        rod_radius=None, rod_segments=16, ray_length_ratio=1.6,
                        tail_length_ratio=0.6):
    """Zeiger wie auf dem Foto der Lübecker Astronomischen Uhr: ein dünnes,
    rundes goldenes Rohr (echter Zylinder) von der Nabe bis zur Spitze, dort
    eine erhabene goldene KUGEL (kein flaches Medaillon) mit einem Kranz aus
    einzelnen, duennen Strahlenzacken (mit sichtbaren Luecken dazwischen -
    keine geschlossene Zackenscheibe), wie im Original. Das Rohr liegt entlang
    der lokalen Y-Achse ("12-Uhr"-Richtung bei Startwinkel 0); die ganze
    Zeiger-Baugruppe rotiert wie gewohnt um die lokale Z-Achse."""
    if rod_radius is None:
        rod_radius = sun_radius * 0.10  # dünn, wie ein Rohr - nicht wie eine Klinge

    bm = bmesh.new()

    # 1) Rohr: von der Rückseite (Gegengewicht) bis in die Kugel hinein
    #    (Überlappung vermeidet eine Lücke).
    tail_length = sun_radius * tail_length_ratio
    add_rod_geometry(bm, rod_radius, -tail_length, length + sun_radius * 0.3, rod_segments)

    # 2) Goldene, gewölbte Kuppe an der Spitze (wie getriebenes Goldblech -
    #    KEINE Vollkugel). Flacher Deckel unten, leichte Wölbung nach oben.
    dome_center = (0.0, length, -sun_radius * 0.15)  # Boden leicht versenkt,
    # damit die Kuppe insgesamt mittig zur Rohr-/Strahlenebene sitzt.
    _add_hemisphere_dome(bm, sun_radius, dome_center, lat_segments=10, lon_segments=24,
                         material_index=0, height_ratio=0.42)

    # 3) Kranz aus einzelnen, duennen Strahlenzacken um die Kugel-Basis, MIT
    #    sichtbaren Luecken dazwischen (nicht als eine durchgehende Zackenscheibe,
    #    sondern als separate, schmale Dreiecke - wie im Original).
    ray_length = sun_radius * ray_length_ratio
    ray_base_half_angle = (2.0 * math.pi / rays) * 0.18  # schmale Basis, deutliche Luecken
    for i in range(rays):
        center_angle = i * (2.0 * math.pi / rays) + math.pi / 2.0
        a0 = center_angle - ray_base_half_angle
        a1 = center_angle + ray_base_half_angle
        base_l = (sun_radius * math.cos(a0), length + sun_radius * math.sin(a0))
        base_r = (sun_radius * math.cos(a1), length + sun_radius * math.sin(a1))
        tip = ((sun_radius + ray_length) * math.cos(center_angle),
               length + (sun_radius + ray_length) * math.sin(center_angle))
        v0 = bm.verts.new((base_l[0], base_l[1], 0.0))
        v1 = bm.verts.new((base_r[0], base_r[1], 0.0))
        v2 = bm.verts.new((tip[0], tip[1], 0.0))
        ray_face = bm.faces.new((v0, v1, v2))
        bmesh.ops.recalc_face_normals(bm, faces=[ray_face])
        extrude_result = bmesh.ops.extrude_face_region(bm, geom=[ray_face])
        extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
        ray_thickness = thickness * 0.4  # Zacken deutlich duenner als die Kugel
        bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, ray_thickness))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def _add_uv_sphere(bm, radius, center, lat_segments=10, lon_segments=16, material_index_fn=None):
    """Baut eine volle UV-Kugel manuell (Nord-/Südpol als Einzel-Vertex, dazwischen
    Breitenkreise). material_index_fn(face_mittelpunkt) kann pro Fläche einen
    Material-Index zurückgeben (z.B. für die halb gold/halb schwarze Mondkugel)."""
    cx, cy, cz = center
    north = bm.verts.new((cx, cy, cz + radius))
    south = bm.verts.new((cx, cy, cz - radius))
    rings = []
    for i in range(1, lat_segments):
        theta = math.pi * i / lat_segments
        z = radius * math.cos(theta) + cz
        ring_r = radius * math.sin(theta)
        ring = []
        for j in range(lon_segments):
            phi = 2.0 * math.pi * j / lon_segments
            x = ring_r * math.cos(phi) + cx
            y = ring_r * math.sin(phi) + cy
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)

    faces = []
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((north, rings[0][j2], rings[0][j])))
    for i in range(len(rings) - 1):
        for j in range(lon_segments):
            j2 = (j + 1) % lon_segments
            faces.append(bm.faces.new((rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j])))
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((south, rings[-1][j], rings[-1][j2])))

    if material_index_fn is not None:
        for f in faces:
            f.material_index = material_index_fn(f.calc_center_median())


def _add_hemisphere_dome(bm, radius, center, lat_segments=8, lon_segments=16,
                         material_index=0, height_ratio=1.0):
    """Baut eine massive, nach oben gewölbte Kuppel (flacher Deckel am Boden
    bei z=center.z, Kuppelspitze bei z=center.z + radius*height_ratio).
    height_ratio=1.0 ergibt eine volle Halbkugel; kleinere Werte (z.B. 0.35)
    ergeben eine flache Wölbung wie ein getriebenes Goldblech (siehe
    Sonnenzeiger) statt einer Kugelhälfte."""
    cx, cy, cz = center
    pole = bm.verts.new((cx, cy, cz + radius * height_ratio))
    rings = []
    for i in range(1, lat_segments + 1):
        theta = (math.pi / 2.0) * i / lat_segments  # 0 an der Kuppelspitze, pi/2 am Rand (Aequator)
        z = radius * height_ratio * math.cos(theta) + cz
        ring_r = radius * math.sin(theta)
        ring = []
        for j in range(lon_segments):
            phi = 2.0 * math.pi * j / lon_segments
            x = ring_r * math.cos(phi) + cx
            y = ring_r * math.sin(phi) + cy
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)

    faces = []
    for j in range(lon_segments):
        j2 = (j + 1) % lon_segments
        faces.append(bm.faces.new((pole, rings[0][j2], rings[0][j])))
    for i in range(len(rings) - 1):
        for j in range(lon_segments):
            j2 = (j + 1) % lon_segments
            faces.append(bm.faces.new((rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j])))
    faces.append(bm.faces.new(list(reversed(rings[-1]))))  # flacher Boden-Deckel

    for f in faces:
        f.material_index = material_index


def add_flat_gear(bm, module, teeth, z_center, thickness, material_index=0,
                  x_offset=0.0, y_offset=0.0):
    """Flaches kleines Zahnrad (echte Evolventenverzahnung) in der lokalen
    XY-Ebene, extrudiert entlang Z - wiederverwendet für alle kleinen
    Getrieberäder der Mondphasen-Mechanik."""
    profile_xy, r_addendum = build_involute_profile(module, teeth)
    verts = [bm.verts.new((x + x_offset, y + y_offset, z_center)) for x, y in profile_xy]
    face = bm.faces.new(verts)
    faces_before = set(bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=[face])
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = material_index
    face.material_index = material_index
    return r_addendum


def build_moon_arm_mesh(name, length, rod_radius, tail_length_ratio, ball_radius, segments=16):
    """Das Rohr des Mondzeigers PLUS die feste schwarze Halbkugel-Schale an der
    Spitze (cupt die Kugel). Keine Platinen/Bodenplatte mehr hier - das war
    nicht originalgetreu. Material-Index 0 = Messing/Gold (Rohr), 1 =
    Schwarzlack (Schale, wie im vom Nutzer bereitgestellten Referenzcode)."""
    bm = bmesh.new()
    tail_length = ball_radius * tail_length_ratio
    add_rod_geometry(bm, rod_radius, -tail_length, length, segments)
    for f in bm.faces:
        f.material_index = 0  # Messing/Gold

    br = ball_radius
    tip_y = length  # an dieser Stelle sitzt die Getriebekapsel (Kind-Objekt)

    # Halbkugel-Schale: cupt die Kugel, Rand liegt auf Hoehe der Kugelmitte,
    # Kuppel zeigt nach hinten (-Z). Schwarz lackiert.
    ball_center_z = br * 0.9
    shell_radius = br * 1.05
    shell_thickness = shell_radius * 0.10
    shell_center = (0.0, tip_y, ball_center_z)
    add_hemisphere_shell(bm, shell_radius, shell_thickness, shell_center,
                         segments=28, rings=12, material_index=1, direction=1.0)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_moon_capsule_mesh(name, ball_radius):
    """Die rotierende Baugruppe an der Mondzeiger-Spitze (Kind-Objekt, eigene
    Differenz-Rotation): nur noch die zweifarbige (halb gold poliert / halb
    schwarz lackiert) Mondphasenkugel - keine eigenen Zahnräder mehr an dieser
    Stelle (das Getriebe sitzt jetzt sichtbar an den Radpaaren 3/4 und 8/9 im
    Hauptgetriebe, siehe build_gear_pair_support_object)."""
    bm = bmesh.new()
    br = ball_radius
    ball_center_z = br * 0.9

    # Mondphasenkugel: zweifarbig (Material 0 = Gold poliert, Material 1 =
    # Schwarzlack), Grenze an der Kugel-eigenen Mitte (= aktuelle "Phasengrenze"),
    # sitzt vorne, ragt aus der Schale (siehe Arm-Mesh) heraus.
    ball_center = (0.0, 0.0, ball_center_z)

    def ball_material(face_center):
        return 0 if face_center.z >= ball_center[2] else 1

    _add_uv_sphere(bm, ball_radius, ball_center, lat_segments=24, lon_segments=32,
                   material_index_fn=ball_material)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_gear_pair_support_mesh(name, z_low, z_high, plate_side="high",
                                 gear_thickness=0.25, shaft_radius=0.30,
                                 plate_radius=5.5, plate_thickness=0.35,
                                 strut_size=1.0, margin=0.3):
    """Sichtbare gemeinsame Achse für ein Zahnradpaar auf einer Welle (z.B. Rad
    3+4 oder Rad 8+9), gehalten zwischen einer Platine (transparent) und einer
    kleinen senkrechten Strebe auf einer Bodenplatte - wie im Original-Schema
    beschrieben. Alle Werte hier sind bereits in Welt-Einheiten (die Gear-
    Objekte selbst liegen ja auch unskaliert an ihrer *SCALE-Position), das
    Objekt bekommt daher location.z = 0 und alles ist direkt in der Mesh-
    Geometrie enthalten.
    plate_side="high": Platine an der oberen (z_high, meist dem Zifferblatt
    zugewandten) Seite, Strebe unten. plate_side="low": umgekehrt."""
    bm = bmesh.new()

    shaft_z0 = z_low - margin
    shaft_z1 = z_high + gear_thickness + margin
    add_rod_along_z(bm, shaft_radius, shaft_z0, shaft_z1, segments=20, material_index=0)

    if plate_side == "high":
        plate_z = shaft_z1 + plate_thickness * 0.5 + 0.1
        strut_z = shaft_z0 - strut_size * 0.5 - 0.1
    else:
        plate_z = shaft_z0 - plate_thickness * 0.5 - 0.1
        strut_z = shaft_z1 + strut_size * 0.5 + 0.1

    add_disc_plate(bm, plate_radius, plate_z, plate_thickness, material_index=1, segments=36)

    down_offset = plate_radius * 0.95
    z_min = min(plate_z, strut_z) - 0.3
    z_max = max(plate_z, strut_z) + 0.3
    add_box(bm, x_range=(-down_offset - 0.25, -down_offset),
            y_range=(-plate_radius * 0.35, plate_radius * 0.35),
            z_range=(z_min, z_max), material_index=0)
    add_box(bm, x_range=(-down_offset, 0.0),
            y_range=(-strut_size * 0.5, strut_size * 0.5),
            z_range=(strut_z - strut_size * 0.5, strut_z + strut_size * 0.5),
            material_index=0)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_gear_pair_support_object(entry, collection, brass_material, transparent_material):
    name = f"Radhalterung_{entry.get('id', '?')}"
    z_low = float(entry["z_low"]) * SCALE
    z_high = float(entry["z_high"]) * SCALE
    mesh = build_gear_pair_support_mesh(
        name, z_low, z_high,
        plate_side=entry.get("plate_side", "high"),
        gear_thickness=float(entry.get("gear_thickness", 0.25)) * SCALE,
        shaft_radius=float(entry.get("shaft_radius", 0.30)),
        plate_radius=float(entry.get("plate_radius", 5.5)),
        plate_thickness=float(entry.get("plate_thickness", 0.35)),
        strut_size=float(entry.get("strut_size", 1.0)),
    )
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        0.0,
    )
    mesh.materials.append(brass_material)
    mesh.materials.append(transparent_material)
    add_bevel_modifier(obj)
    return obj


def build_moon_center_gear_mesh(name):
    """Winziges, dekoratives 'Zentralrad auf der Sonnenzeiger-Welle' (siehe
    Getriebe.jpg) - dreht mit dem Sonnenzeiger, sitzt mittig auf der Uhr."""
    bm = bmesh.new()
    gear_profile_xy, r_addendum = build_involute_profile(MOON_GEAR_MODULE, MOON_GEAR_TEETH)
    thickness = r_addendum * 0.6
    verts_bottom = [bm.verts.new((x, y, 0.0)) for x, y in gear_profile_xy]
    face_bottom = bm.faces.new(verts_bottom)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=[face_bottom])
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_star_disc_mesh(name, radius, star_count=90, star_size=0.22, seed=42, segments=96):
    """Sternscheibe: dunkelblaue Kreisscheibe mit kleinen, STARREN goldenen
    Sternen (Material-Index 1), die Teil DESSELBEN Mesh sind wie die Scheibe
    selbst - sie drehen sich also zwangslaeufig MIT der Scheibe (kein
    Gegengewicht, im Gegensatz zu den Tierkreisfiguren, die als separate
    Kind-Objekte gebaut werden, siehe build_zodiac_figure_object)."""
    bm = bmesh.new()

    # Scheibe (dunkelblauer Hintergrund, Material-Index 0)
    disc_verts = [
        bm.verts.new((radius * math.cos(2 * math.pi * i / segments),
                      radius * math.sin(2 * math.pi * i / segments), 0.0))
        for i in range(segments)
    ]
    bm.faces.new(disc_verts)
    for f in bm.faces:
        f.material_index = 0

    faces_before = set(bm.faces)
    rng = random.Random(seed)
    for _ in range(star_count):
        r = radius * 0.94 * math.sqrt(rng.random())  # gleichverteilt über die Fläche
        angle = rng.uniform(0.0, 2.0 * math.pi)
        cx, cy = r * math.cos(angle), r * math.sin(angle)
        # kleiner, vierzackiger Stern (einfaches Rautenkreuz)
        n = 8
        pts = []
        for i in range(n):
            a = 2.0 * math.pi * i / n
            rr = star_size if i % 2 == 0 else star_size * 0.4
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        verts = [bm.verts.new((x, y, 0.0)) for x, y in pts]
        bm.faces.new(verts)

    # Sterne leicht erhaben (Relief) ueber die Scheibenoberflaeche extrudieren
    new_faces = [f for f in bm.faces if f not in faces_before]
    bmesh.ops.recalc_face_normals(bm, faces=new_faces)
    extrude_result = bmesh.ops.extrude_face_region(bm, geom=new_faces)
    extruded_verts = [v for v in extrude_result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, star_size * 0.3))
    for f in bm.faces:
        if f not in faces_before:
            f.material_index = 1  # golden

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_star_disc_object(entry, collection, star_disc_material, brass_material, fps):
    name = f"Sternscheibe_{entry.get('id', '?')}"
    radius = float(entry.get("radius", 17.5))
    image_filename = entry.get("image")

    if image_filename:
        # Echtes Sternhimmel-Bild als Textur - ersetzt die prozeduralen Sterne
        # 1:1 durch die Originalgrafik (dieselbe UV-Mapping-Logik wie beim
        # Zifferblatt, da beides randfuellende Kreisbilder sind).
        mesh = build_dial_mesh(name, radius)
        material, _aspect = get_or_create_figure_material(image_filename)
        materials_to_assign = [material]
    else:
        star_count = int(entry.get("star_count", 90))
        mesh = build_star_disc_mesh(name, radius, star_count=star_count)
        materials_to_assign = [star_disc_material, brass_material]

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    for mat in materials_to_assign:
        mesh.materials.append(mat)

    direction = float(entry.get("dir", STAR_DISC_DIR))
    speed = float(entry.get("speed", STAR_DISC_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)
    return obj, direction, speed


def build_zodiac_figure_mesh(name, height, aspect_ratio, vertical_anchor="bottom"):
    """Flache Bild-Ebene für ein Tierkreiszeichen (echtes PNG mit Transparenz,
    kein Platzhalter-Modell nötig). Liegt in der lokalen XY-Ebene, "oben"
    (Bildkopf) entlang lokal +Y, UV-Koordinaten decken das Bild exakt ab.
    Seitenverhältnis (aspect_ratio = Bildbreite/-höhe) sorgt dafür, dass das
    Bild nicht verzerrt wird. vertical_anchor="bottom": Ankerpunkt (0,0) liegt
    an der Unterkante (wie bei stehenden Figuren, "Fuesse" am Orbit-Punkt);
    "center": Ankerpunkt liegt in der Bildmitte (fuer das zentrale, kreisrunde
    Heiland-Medaillon)."""
    half_h = height * 0.5
    half_w = height * aspect_ratio * 0.5
    y_bottom = -half_h if vertical_anchor == "center" else 0.0
    y_top = half_h if vertical_anchor == "center" else height

    bm = bmesh.new()
    v_bl = bm.verts.new((-half_w, y_bottom, 0.0))
    v_br = bm.verts.new((half_w, y_bottom, 0.0))
    v_tr = bm.verts.new((half_w, y_top, 0.0))
    v_tl = bm.verts.new((-half_w, y_top, 0.0))
    face = bm.faces.new((v_bl, v_br, v_tr, v_tl))
    bmesh.ops.recalc_face_normals(bm, faces=[face])

    uv_layer = bm.loops.layers.uv.new()
    uv_coords = {v_bl: (0.0, 0.0), v_br: (1.0, 0.0), v_tr: (1.0, 1.0), v_tl: (0.0, 1.0)}
    for loop in face.loops:
        loop[uv_layer].uv = uv_coords[loop.vert]

    mesh = bpy.data.meshes.new(name + "_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def build_zodiac_figure_object(entry, collection, fps, parent_obj, parent_dir, parent_speed):
    """Baut eine Tierkreisfigur (aus dem mitgelieferten PNG-Bild) als KIND-
    Objekt der Sternscheibe und sorgt für die "schwerkraftgefuehrte" aufrechte
    Haltung:

    PHYSIKALISCHER HINTERGRUND: Am Original haengt hinter jeder Figur ein
    Gegengewicht. Dreht sich die Sternscheibe, sorgt die Schwerkraft dafuer,
    dass das Gewicht immer nach unten haengt - die Figur behaelt dadurch ihre
    absolute (Welt-)Ausrichtung bei, waehrend sie mit der Scheibe auf einer
    Kreisbahn "mitfaehrt". Das ist exakt das Prinzip einer Riesenrad-Gondel:
    Die Gondel umkreist die Radnabe, dreht sich dabei aber NICHT um die
    eigene Achse.

    UMSETZUNG (ohne Physik-Simulation, rein kinematisch): Die Figur wird als
    Kind-Objekt der Scheibe positioniert (ihre ORBITALE Position - der Umlauf
    um das Scheibenzentrum - ergibt sich dadurch automatisch aus der Scheiben-
    rotation). Zusaetzlich bekommt sie ihre EIGENE Rotationsanimation um die
    lokale Z-Achse mit exakt ENTGEGENGESETZTER Drehrichtung/-geschwindigkeit
    der Scheibe. Da beide Rotationen um dieselbe Achse (Z) erfolgen, addieren
    sie sich einfach: Welt-Rotation der Figur = Scheiben-Rotation + Figur-
    Eigenrotation = Scheiben-Rotation + (-Scheiben-Rotation) = 0 - die Figur
    steht also zu JEDEM Zeitpunkt exakt so aufrecht wie beim Start, ohne dass
    einzelne Keyframes pro Figur von Hand berechnet werden muessen (effizient:
    nur 2 Keyframes + F-Curve-Extrapolation, wie ueberall sonst im Skript).

    UNTERSCHIEDLICHE LOKALE ACHSEN: Falls ein Bild nicht mit "oben" = +Y
    ausgerichtet ist, kann `model_rotation_correction_deg` einen einmaligen,
    STATISCHEN Korrekturwinkel (in Grad, um die lokale Z-Achse) vorgeben -
    dieser wird direkt ins Mesh gebacken (nicht mit-animiert), sodass die
    Gegenrotation unabhaengig davon exakt aufgeht.
    """
    orbit_radius = float(entry.get("orbit_radius", 12.0))
    angle_deg = float(entry.get("angle_deg", 0.0))
    angle = math.radians(angle_deg)
    correction_deg = float(entry.get("model_rotation_correction_deg", 0.0))
    height = float(entry.get("height", 3.94))
    # Freier Feinversatz (in denselben Welt-Einheiten wie orbit_radius) - wird
    # NACH der Kreisformel addiert, damit man eine Figur bei Bedarf einfach
    # "nachschieben" kann, ohne angle_deg/orbit_radius neu ausrechnen zu muessen.
    x_offset = float(entry.get("x_offset", 0.0))
    y_offset = float(entry.get("y_offset", 0.0))
    image_filename = entry["image"]

    material, aspect_ratio = get_or_create_figure_material(image_filename)

    name = f"Tierkreiszeichen_{entry.get('id', '?')}"
    vertical_anchor = entry.get("vertical_anchor", "center" if orbit_radius == 0.0 else "bottom")
    mesh = build_zodiac_figure_mesh(name, height, aspect_ratio, vertical_anchor=vertical_anchor)

    # Statische Achsenkorrektur direkt in die Mesh-Geometrie backen (siehe
    # Docstring) - dreht NUR die Vertices, keine Objekt-Rotation, damit die
    # spaetere Gegenrotations-Animation unangetastet bleibt.
    if abs(correction_deg) > 1e-9:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.rotate(bm, verts=bm.verts,
                         cent=(0.0, 0.0, 0.0),
                         matrix=mathutils.Matrix.Rotation(math.radians(correction_deg), 3, 'Z'))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    # Position IM LOKALEN Koordinatensystem der Sternscheibe (nicht *SCALE,
    # da die Scheibe selbst schon in "finalen" Welt-Einheiten gebaut ist -
    # dieselbe Konvention wie bei der Mondzeiger-Kapsel).
    obj.location = (orbit_radius * math.cos(angle) + x_offset,
                    orbit_radius * math.sin(angle) + y_offset, 0.05)
    obj.rotation_euler = (0.0, 0.0, 0.0)

    mesh.materials.append(material)

    obj.parent = parent_obj  # erbt Umlaufbewegung der Scheibe automatisch

    # Exakte Gegenrotation: gleiche Geschwindigkeit, entgegengesetzte Richtung.
    animate_spin(obj, "z", -parent_dir, parent_speed, fps)
    return obj


def build_hand_object(entry, collection, material, fps):
    length = float(entry.get("length", 17.0))
    sun_radius = float(entry.get("sun_radius", 3.2))
    rays = int(entry.get("rays", 12))
    thickness = float(entry.get("thickness", 0.35))

    name = f"Zeiger_{entry.get('id', '?')}"
    mesh = build_sun_hand_mesh(name, length, sun_radius, rays, thickness)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    add_bevel_modifier(obj)

    # Bewusst identisch zu Rad 6 (+5): dieselbe Achse, dieselbe Drehrichtung/-geschwindigkeit.
    direction = float(entry.get("dir", SHAFT_56_DIR))
    speed = float(entry.get("speed", SHAFT_56_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)

    return obj


def build_moon_hand_object(entry, collection, brass_material, moon_material, transparent_material, fps):
    """Baut den Mondzeiger als ZWEI Objekte: den Arm (rotiert einmal pro Monat
    mit der Mondzeiger-Welle, also Rad 10; trägt außerdem die feste Schale +
    Platinen + Streben + Bodenplatte) und die Getriebe-Kapsel (Welle mit vier
    Zahnrädern + Kugel) als KIND-Objekt an der Spitze. Die Kapsel erbt die
    Arm-Rotation automatisch durchs Parenting und bekommt zusätzlich ihre
    EIGENE, unabhängige Rotation - genau die Differenz aus Mondzeiger- und
    Sonnenzeiger-Wellendrehzahl, wie beim historischen Planetengetriebe
    (24:24-Räder, siehe Getriebe.jpg)."""
    length = float(entry.get("length", 14.5))
    ball_radius = float(entry.get("ball_radius", 1.1))
    rod_radius_ratio = float(entry.get("rod_radius_ratio", 0.16))
    tail_length_ratio = float(entry.get("tail_length_ratio", 0.6))
    rod_radius = ball_radius * rod_radius_ratio

    axis_letter = str(entry.get("axis", "z")).lower()
    arm_dir = float(entry.get("dir", SHAFT_10_DIR))
    arm_speed = float(entry.get("speed", SHAFT_10_SPEED))

    # --- 1) Der Arm (Elternobjekt): Rohr + feste Schale/Platinen/Streben/Bodenplatte ---
    arm_name = f"Zeiger_{entry.get('id', '?')}"
    arm_mesh = build_moon_arm_mesh(arm_name, length, rod_radius, tail_length_ratio, ball_radius)
    arm_obj = bpy.data.objects.new(arm_name, arm_mesh)
    collection.objects.link(arm_obj)
    arm_obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    arm_obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])
    arm_mesh.materials.append(brass_material)  # Index 0: Messing/Gold (Rohr)
    arm_mesh.materials.append(moon_material)  # Index 1: Schwarzlack (Schale)
    add_bevel_modifier(arm_obj)
    animate_spin(arm_obj, axis_letter, arm_dir, arm_speed, fps)

    # --- 2) Die Getriebe-Kapsel (Kind-Objekt, eigene Rotation) ---
    capsule_name = f"Getriebekapsel_{entry.get('id', '?')}"
    capsule_mesh = build_moon_capsule_mesh(capsule_name, ball_radius)
    capsule_obj = bpy.data.objects.new(capsule_name, capsule_mesh)
    collection.objects.link(capsule_obj)
    # Position IM LOKALEN Koordinatensystem des Arms (an dessen Spitze, y=length,
    # in denselben unskalierten Einheiten wie das Rohr-Mesh selbst).
    capsule_obj.location = (0.0, length, 0.0)
    capsule_obj.rotation_euler = (0.0, 0.0, 0.0)
    capsule_mesh.materials.append(brass_material)  # Index 0: Messing/Gold
    capsule_mesh.materials.append(moon_material)  # Index 1: Schwarzlack
    add_bevel_modifier(capsule_obj)

    capsule_obj.parent = arm_obj  # erbt Position/Rotation des Arms automatisch

    # Eigene, ZUSAETZLICHE Rotation der Kapsel = Differenz zwischen Mondzeiger-
    # und Sonnenzeiger-Wellendrehzahl (1:1-Übersetzung, wie die beiden
    # historischen 24-Zähne-Räder). Das ist die eigentliche "Mondphasen"-Bewegung.
    sun_dir = SHAFT_56_DIR
    sun_speed = SHAFT_56_SPEED
    differential = (arm_dir * arm_speed) - (sun_dir * sun_speed)
    animate_spin(capsule_obj, "z", 1.0 if differential >= 0 else -1.0, abs(differential), fps)

    return arm_obj


def build_moon_center_gear_object(entry, collection, brass_material, fps):
    name = f"Zentralrad_{entry.get('id', '?')}"
    mesh = build_moon_center_gear_mesh(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )
    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])
    if mesh.materials:
        mesh.materials[0] = brass_material
    else:
        mesh.materials.append(brass_material)
    add_bevel_modifier(obj)

    direction = float(entry.get("dir", SHAFT_56_DIR))
    speed = float(entry.get("speed", SHAFT_56_SPEED))
    animate_spin(obj, axis_letter, direction, speed, fps)
    return obj


def add_bevel_modifier(obj):
    bevel = obj.modifiers.new(name="Kantenverrundung", type='BEVEL')
    bevel.width = BEVEL_WIDTH
    bevel.segments = 3
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(35.0)


def animate_spin(obj, axis_letter, direction, speed, fps):
    """Setzt eine linear extrapolierte Dreh-Animation um die lokale Z-Achse."""
    total_seconds = CYCLE_FRAMES / fps
    target_angle = direction * speed * BASE_ANGULAR_SPEED * total_seconds

    obj.rotation_mode = 'XYZ'
    z_index = 2  # lokale Z-Achse

    obj.rotation_euler[z_index] = 0.0
    obj.keyframe_insert(data_path="rotation_euler", index=z_index, frame=1)
    obj.rotation_euler[z_index] = target_angle
    obj.keyframe_insert(data_path="rotation_euler", index=z_index, frame=1 + CYCLE_FRAMES)

    # Korrigierter Zugriff für Blender 4.x+
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        curves = getattr(action, "fcurves", None)
        if curves is None:
            curves = getattr(action, "curves", [])

        fcurve = next(
            (fc for fc in curves if fc.data_path == "rotation_euler" and fc.array_index == z_index),
            None,
        )
        if fcurve is not None:
            fcurve.extrapolation = 'LINEAR'
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = 'LINEAR'


def build_gear_object(entry, collection, material, fps):
    # Zuerst prüfen, ob Zähnezahl da ist, sonst Fallback über einen groben Radius-Wunsch
    if "teeth" in entry:
        teeth = int(entry["teeth"])
    else:
        outer_r_input = float(entry.get("r", 2.0))
        teeth = compute_teeth_count(outer_r_input * SCALE)

    # --- ECHTE EVOLVENTEN-RADIEN ÜBER DAS MODUL ---
    # r_pitch (Wälzkreis) ist die Grundlage für den korrekten Mittenabstand kämmender
    # Räder (Positionen in GEAR_DATA sind entsprechend darauf abgestimmt).
    # r_addendum (Kopfkreis) ist der tatsächliche, sichtbare Außenradius.
    r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(GEAR_MODULE, teeth)
    outer_radius = r_addendum
    # -----------------------------------------------

    # Feste Dicke oder Standard-Verhältnis
    if "thickness" in entry:
        thickness = float(entry["thickness"]) * SCALE
    else:
        thickness = outer_radius * GEAR_THICKNESS_RATIO

    name = f"Zahnrad_{entry.get('id', '?')}"
    spoked = bool(entry.get("spoked", False))
    mesh = build_gear_mesh(name, GEAR_MODULE, teeth, thickness, outer_radius_dev=outer_radius,
                           spoked=spoked)

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)

    obj.location = (
        float(entry.get("x", 0.0)) * SCALE,
        float(entry.get("y", 0.0)) * SCALE,
        float(entry.get("z", 0.0)) * SCALE,
    )

    axis_letter = str(entry.get("axis", "z")).lower()
    obj.rotation_euler = AXIS_ALIGN_EULER.get(axis_letter, AXIS_ALIGN_EULER["z"])

    if mesh.materials:
        mesh.materials[0] = material
    else:
        mesh.materials.append(material)

    add_bevel_modifier(obj)

    direction = float(entry.get("dir", 1))
    speed = float(entry.get("speed", 1))
    animate_spin(obj, axis_letter, direction, speed, fps)

    return obj


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base if scene.render.fps_base else scene.render.fps
    scene.frame_end = max(scene.frame_end, 1 + CYCLE_FRAMES)

    collection = get_or_create_collection(COLLECTION_NAME)
    clear_collection(collection)

    brass_material = get_or_create_brass_material()
    steel_material = get_or_create_steel_material()
    axle_steel_material = get_or_create_axle_steel_material()
    transparent_material = get_or_create_transparent_material()
    dial_material = get_or_create_dial_material()
    moon_material = get_or_create_moon_material()
    star_disc_material = get_or_create_star_disc_material()
    gear_data = load_gear_data()

    created = []
    named_objects = {}  # id -> Objekt (fuer Parent-Lookups, z.B. Sternscheibe)
    disc_spin_by_id = {}  # id -> (dir, speed) der jeweiligen Scheibe
    for entry in gear_data:
        etype = entry.get("type", "gear")
        if etype == "gear":
            obj = build_gear_object(entry, collection, steel_material, fps)
            created.append(obj)
        elif etype == "axis":
            obj = build_axis_object(entry, collection, brass_material, transparent_material, axle_steel_material)
            created.append(obj)
        elif etype == "dial":
            obj = build_dial_object(entry, collection, dial_material)
            created.append(obj)
        elif etype == "hand":
            obj = build_hand_object(entry, collection, brass_material, fps)
            created.append(obj)
        elif etype == "moon_hand":
            obj = build_moon_hand_object(entry, collection, brass_material, moon_material, transparent_material, fps)
            created.append(obj)
        elif etype == "moon_center_gear":
            obj = build_moon_center_gear_object(entry, collection, brass_material, fps)
            created.append(obj)
        elif etype == "gear_pair_support":
            obj = build_gear_pair_support_object(entry, collection, brass_material, transparent_material)
            created.append(obj)
        elif etype == "star_disc":
            obj, disc_dir, disc_speed = build_star_disc_object(
                entry, collection, star_disc_material, brass_material, fps)
            created.append(obj)
            named_objects[entry.get("id")] = obj
            disc_spin_by_id[entry.get("id")] = (disc_dir, disc_speed)
        elif etype == "zodiac_figure":
            parent_id = entry.get("parent_id")
            parent_obj = named_objects.get(parent_id)
            if parent_obj is None:
                print(f"[Sternscheibe] WARNUNG: parent_id '{parent_id}' fuer Tierkreisfigur "
                      f"'{entry.get('id')}' nicht gefunden (Sternscheibe muss VOR den Figuren "
                      f"in GEAR_DATA stehen) - Figur wird uebersprungen.")
                continue
            parent_dir, parent_speed = disc_spin_by_id[parent_id]
            obj = build_zodiac_figure_object(entry, collection, fps,
                                             parent_obj, parent_dir, parent_speed)
            created.append(obj)

    print(f"[Messingzahnraeder] {len(created)} Objekte erzeugt in Collection '{COLLECTION_NAME}'.")
    for obj, entry in zip(created, [e for e in gear_data if e.get("type") == "gear"]):
        teeth = int(entry["teeth"])
        r_pitch, r_base, r_addendum, r_dedendum = compute_gear_radii(GEAR_MODULE, teeth)
        print(f"  - {obj.name}: {teeth} Zähne -> Wälzkreis {r_pitch:.2f} / Kopfkreis {r_addendum:.2f}, "
              f"speed={entry.get('speed')}, dir={entry.get('dir')}")


if __name__ == "__main__":
    main()