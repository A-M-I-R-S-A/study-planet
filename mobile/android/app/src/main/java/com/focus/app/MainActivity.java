package com.focus.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Registered before super so the bridge picks them up while building the WebView.
        registerPlugin(FocusPlugin.class);
        registerPlugin(MusicPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
