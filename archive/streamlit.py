import archive.streamlit as st
from ultralytics import YOLO
import os
from PIL import Image
import cv2 
import numpy as np

# --- KONFIGURASI MODEL ---
PATH_MODEL_1 = "model_1.pt"  # Untuk umur <= 15 hari
PATH_MODEL_2 = "model_2.pt"  # Untuk umur > 15 hari
# -------------------------


@st.cache_resource  # Meng-cache model agar tidak di-load ulang setiap kali
def load_model(umur):
    """
    Memilih path model berdasarkan umur (tanpa menampilkan log ke UI), 
    memvalidasi keberadaan file, dan me-load model YOLO yang di-cache.
    """
    path_to_check = ""
    model_name_placeholder = ""
    
    if umur <= 15:
        path_to_check = PATH_MODEL_1
        model_name_placeholder = "yolov8n.pt" # Placeholder jika model_1.pt tidak ada
    else:
        path_to_check = PATH_MODEL_2
        model_name_placeholder = "yolov8s.pt" # Placeholder jika model_2.pt tidak ada

    final_model_path = ""
    # Cek jika file model kustom ada
    if os.path.exists(path_to_check):
        final_model_path = path_to_check
    else:
        # Jika tidak ada, gunakan model placeholder standar
        final_model_path = model_name_placeholder

    # Muat model YOLO
    try:
        model = YOLO(final_model_path)
        return model
    except Exception as e:
        # Biarkan error ini agar pengguna tahu jika model gagal dimuat
        st.error(f"Gagal memuat model {final_model_path}. Kesalahan: {e}")
        return None

# --- UI STREAMLIT ---

# Gunakan layout="wide" agar kolom kanan-kiri terlihat bagus
st.set_page_config(page_title="Deteksi Kentang", page_icon="🥔", layout="wide")

st.title("Pendeteksi Pertumbuhan Kentang Cepat 🥔")
st.write("Unggah gambar dan masukkan umur untuk prediksi otomatis.")

st.divider()

# --- Tata Letak Kanan-Kiri ---
input_col, output_col = st.columns(2)

# --- Kolom Input (Kiri) ---
with input_col:
    st.subheader("Input Kontrol")
    umur_tanaman = st.number_input(
        "Masukkan Umur Tanaman (hari)", 
        min_value=0, 
        step=1, 
        value=10,
        help="Masukkan 15 atau kurang untuk Model 1, lebih dari 15 untuk Model 2."
    )

    uploaded_file = st.file_uploader(
        "Unggah Gambar Kentang", 
        type=["jpg", "jpeg", "png"]
    )

# --- Kolom Output (Kanan) ---
with output_col:
    # --- Logika Prediksi dan Tampilan Hasil (Otomatis) ---
    if uploaded_file is not None:
        # 1. Buka gambar yang diunggah
        image = Image.open(uploaded_file)
        
        # 2. Logika prediksi berjalan otomatis setelah gambar diunggah
        with st.spinner("Sedang memproses, harap tunggu..."):
            try:
                # 3. Muat model yang sesuai (menggunakan cache)
                model = load_model(umur_tanaman)
                
                if model:
                    # 4. Jalankan prediksi
                    image_np = np.array(image)
                    results = model.predict(image_np)
                    
                    # Cek apakah ada hasil dan ada box
                    if results and results[0].boxes and len(results[0].boxes) > 0:
                        st.subheader("Hasil Prediksi")
                        
                        # 5. Ambil gambar hasil (dengan bounding box)
                        result_plot_bgr = results[0].plot()
                        result_plot_rgb = cv2.cvtColor(result_plot_bgr, cv2.COLOR_BGR2RGB)
                        
                        # Tampilkan gambar hasil
                        st.image(result_plot_rgb, caption="Gambar hasil deteksi.", use_container_width=True)
                        st.success("Prediksi berhasil!")

                        # 6. Tampilkan ringkasan sederhana di bawah hasil
                        st.subheader("Ringkasan Deteksi")
                        boxes = results[0].boxes
                        class_indices = boxes.cls.int().tolist()
                        class_names = [results[0].names[i] for i in class_indices]
                        
                        counts = {}
                        for name in class_names:
                            counts[name] = counts.get(name, 0) + 1
                            
                        if counts:
                            for name, count in counts.items():
                                st.write(f"- Terdeteksi **{count}** objek **'{name}'**")
                        else:
                            st.write("Objek terdeteksi tetapi nama kelas tidak ditemukan.")

                    else:
                        st.warning("Model berhasil berjalan, tetapi tidak ada objek yang terdeteksi.")
                        # Jika tidak ada deteksi, tampilkan gambar asli agar pengguna tahu
                        st.subheader("Gambar Asli (Tidak Ada Deteksi)")
                        st.image(image, caption="Gambar yang diunggah.", use_container_width=True)
                        
            except Exception as e:
                st.error(f"Terjadi kesalahan saat melakukan prediksi: {e}")
    else:
        # Pesan placeholder untuk kolom kanan
        st.info("Silakan unggah gambar di sebelah kiri untuk memulai prediksi.")