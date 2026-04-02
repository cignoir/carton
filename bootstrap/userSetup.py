# --- Carton Bootstrap ---
try:
    import carton_bootstrap
    carton_bootstrap.start()
except Exception as e:
    import traceback
    print("[Carton] Bootstrap failed: {}".format(e))
    traceback.print_exc()
# --- End Carton Bootstrap ---
