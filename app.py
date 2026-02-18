import streamlit as st
import pandas as pd
import io

# Configuración visual
st.set_page_config(page_title="Actualizador Ternium > Odoo", layout="wide", page_icon="🏭")
st.title("🏭 Actualizador de Precios: Ternium a Odoo")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("1. Subir Archivos")
    st.info("Tip: Si tu archivo de Odoo tiene la columna 'ID externo', el sistema la usará para evitar duplicados.")
    file_odoo = st.file_uploader("📂 Archivo de Odoo (CSV/Excel)", type=['csv', 'xlsx'])
    file_ternium = st.file_uploader("📂 Catálogo Ternium (CSV/Excel)", type=['csv', 'xlsx'])

# --- LÓGICA PRINCIPAL ---
if file_ternium and file_odoo:
    try:
        # 1. CARGAR TERNIUM (Forzando la Fila 3 como cabecera)
        if file_ternium.name.endswith('.csv'):
            df_ternium = pd.read_csv(file_ternium, header=2)
        else:
            df_ternium = pd.read_excel(file_ternium, header=2)

        col_clave_ternium = 'Clave producto'
        if col_clave_ternium not in df_ternium.columns:
            st.error(f"❌ Error: No encuentro la columna '{col_clave_ternium}' en Ternium.")
            st.stop()

        # 2. CARGAR ODOO
        # Leemos todo como string primero para proteger los datos
        if file_odoo.name.endswith('.csv'):
            df_odoo = pd.read_csv(file_odoo, dtype=str) 
        else:
            df_odoo = pd.read_excel(file_odoo, dtype=str)

        # Definición de columnas
        col_ref_interna = 'Referencia interna'
        col_id_externo = 'ID externo' # Esta es la columna mágica
        col_ternium_en_odoo = 'x_ternium_id'
        col_peso = 'Peso' 

        # Validaciones básicas
        errores = []
        if col_ternium_en_odoo not in df_odoo.columns: errores.append(f"Falta '{col_ternium_en_odoo}' en Odoo.")
        if col_peso not in df_odoo.columns: errores.append(f"Falta '{col_peso}' en Odoo.")
        
        # Lógica inteligente para elegir qué ID usar
        usar_id_externo = False
        col_id_usada = '' # Aquí guardaremos cuál vamos a usar

        if col_id_externo in df_odoo.columns:
            usar_id_externo = True
            col_id_usada = col_id_externo
        elif col_ref_interna in df_odoo.columns:
            col_id_usada = col_ref_interna
            st.warning("⚠️ No encontré 'ID externo'. Usaré 'Referencia interna'. Cuidado con los productos que pierden los ceros.")
        else:
            errores.append("Falta 'ID externo' (o Referencia interna) en el archivo de Odoo.")

        if errores:
            for e in errores: st.error(e)
            st.stop()

        # 3. LIMPIEZA
        df_odoo_clean = df_odoo.dropna(subset=[col_ternium_en_odoo]).copy()
        
        # Limpieza de IDs Ternium y Referencias
        df_odoo_clean[col_ternium_en_odoo] = df_odoo_clean[col_ternium_en_odoo].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        # Limpiamos también la columna ID que vayamos a usar
        df_odoo_clean[col_id_usada] = df_odoo_clean[col_id_usada].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        
        # Ternium
        df_ternium[col_clave_ternium] = df_ternium[col_clave_ternium].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        
        # Rellenar ceros ID Ternium (para asegurar el match)
        df_odoo_clean[col_ternium_en_odoo] = df_odoo_clean[col_ternium_en_odoo].apply(lambda x: x.zfill(10))
        df_ternium[col_clave_ternium] = df_ternium[col_clave_ternium].apply(lambda x: x.zfill(10))

        # 4. CRUCE (MERGE)
        df_merged = pd.merge(
            df_odoo_clean,
            df_ternium,
            left_on=col_ternium_en_odoo,
            right_on=col_clave_ternium,
            how='inner'
        )

        if df_merged.empty:
            st.warning("⚠️ No se encontraron coincidencias. Verificá los IDs.")
            st.stop()

        # 5. CÁLCULOS
        def clean_money(x):
            if isinstance(x, str):
                return float(x.replace('$', '').replace(',', ''))
            return float(x) if pd.notnull(x) else 0.0

        precio_col = 'Precio con envío USD'
        if precio_col not in df_merged.columns:
            st.error(f"No encuentro la columna '{precio_col}' en Ternium.")
            st.stop()

        df_merged[precio_col] = df_merged[precio_col].apply(clean_money)
        df_merged[col_peso] = pd.to_numeric(df_merged[col_peso], errors='coerce').fillna(0)

        # Fórmula
        df_merged['Nuevo Costo'] = (df_merged[precio_col] / 1000) * df_merged[col_peso]
        df_merged['Nuevo Costo'] = df_merged['Nuevo Costo'].fillna(0)

        # 6. SEPARACIÓN
        # Grupo A: Listos para importar
        df_importar = df_merged[df_merged['Nuevo Costo'] > 0.01].copy()
        # Grupo B: Errores (Precio 0)
        df_revision = df_merged[df_merged['Nuevo Costo'] <= 0.01].copy()

        # Agregamos columna de diagnóstico al de revisión
        def diagnostico(row):
            if row[col_peso] == 0: return "Falta PESO en Odoo"
            if row[precio_col] == 0: return "Precio 0 en Ternium"
            return "Error desconocido"
            
        if not df_revision.empty:
            df_revision['Motivo Error'] = df_revision.apply(diagnostico, axis=1)

        # 7. RESULTADOS Y DESCARGAS
        st.success(f"✅ Proceso terminado. Se usarán {len(df_importar)} productos.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Listos para Importar", len(df_importar))
            if not df_importar.empty:
                # --- AQUÍ ESTÁ EL CAMBIO: Agregué col_ternium_en_odoo a la lista ---
                st.dataframe(df_importar[[col_id_usada, col_ternium_en_odoo, 'Nombre', 'Nuevo Costo']].head())
                
                # Generar CSV Limpio para Odoo
                df_export = pd.DataFrame()
                
                # LA GRAN DIFERENCIA: Usamos 'id' si es externo, 'default_code' si es referencia
                if usar_id_externo:
                    df_export['id'] = df_importar[col_id_usada]
                else:
                    df_export['default_code'] = df_importar[col_id_usada]
                
                # Opcional: Agregar nombre si existe
                if 'Nombre' in df_importar.columns:
                    df_export['name'] = df_importar['Nombre']
                    
                df_export['standard_price'] = df_importar['Nuevo Costo'].round(2)

                csv = df_export.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="💾 1. Descargar CSV para Odoo",
                    data=csv,
                    file_name='actualizacion_precios_ternium.csv',
                    mime='text/csv',
                    key='btn_csv'
                )

        with col2:
            st.metric("Errores / Precio 0", len(df_revision))
            if not df_revision.empty:
                # También lo agregué aquí para ver cuál es el ID Ternium que falló
                st.dataframe(df_revision[[col_id_usada, col_ternium_en_odoo, 'Nombre', 'Motivo Error']].head())
                
                # Generar Excel para revisar
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_revision[[col_id_usada, col_ternium_en_odoo, 'Nombre', col_peso, precio_col, 'Nuevo Costo', 'Motivo Error']].to_excel(writer, index=False)
                
                st.download_button(
                    label="⚠️ 2. Descargar Reporte de Errores",
                    data=output.getvalue(),
                    file_name='productos_con_error.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key='btn_error'
                )

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("👈 Subí los archivos para empezar.")