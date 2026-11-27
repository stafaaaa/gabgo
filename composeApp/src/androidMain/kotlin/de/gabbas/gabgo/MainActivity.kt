package de.gabbas.gabgo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import de.gabbas.gabgo.platform.AndroidPlatform

class MainActivity : ComponentActivity() {
    private val scanLauncher = registerForActivityResult(ScanContract()) { result ->
        AndroidPlatform.deliverScanResult(result.contents)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        AndroidPlatform.attach(this) {
            scanLauncher.launch(
                ScanOptions()
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                    .setPrompt("Vibe-QR-Code scannen")
                    .setBeepEnabled(false)
                    .setOrientationLocked(false),
            )
        }
        setContent { App() }
    }

    override fun onDestroy() {
        AndroidPlatform.detach(this)
        super.onDestroy()
    }
}
