package com.sophyane.companion;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.TimePicker;
import android.widget.Toast;

public final class MainActivity extends Activity {
    private static final int NOTIFICATION_PERMISSION_REQUEST = 9001;

    private TimePicker timePicker;
    private EditText labelInput;
    private TextView statusText;
    private Button permissionButton;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(R.layout.activity_main);

        timePicker = findViewById(R.id.timePicker);
        labelInput = findViewById(R.id.labelInput);
        statusText = findViewById(R.id.statusText);
        permissionButton = findViewById(R.id.permissionButton);

        timePicker.setIs24HourView(true);

        findViewById(R.id.createButton).setOnClickListener(view -> {
            requestNotificationPermissionIfNeeded();

            if (!AlarmScheduler.canScheduleExact(this)) {
                showExactAlarmPermission();
                return;
            }

            createAlarm(
                    timePicker.getHour(),
                    timePicker.getMinute(),
                    labelInput.getText().toString()
            );
        });

        permissionButton.setOnClickListener(
                view -> showExactAlarmPermission()
        );

        findViewById(R.id.cancelButton).setOnClickListener(view -> {
            AlarmScheduler.cancel(this);
            AlarmReceiver.cancelNotification(this);
            refreshStatus();

            Toast.makeText(
                    this,
                    "Saved alarm cancelled",
                    Toast.LENGTH_SHORT
            ).show();
        });

        handleIntent(getIntent());
        refreshStatus();
        refreshPermissionState();
        requestNotificationPermissionIfNeeded();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
        refreshPermissionState();
    }

    private void handleIntent(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();

        if (
                uri == null
                || !"sophyane".equals(uri.getScheme())
                || !"alarm".equals(uri.getHost())
                || !"/create".equals(uri.getPath())
        ) {
            return;
        }

        int hour = parseInt(uri.getQueryParameter("hour"), 7);
        int minute = parseInt(uri.getQueryParameter("minute"), 0);
        String label = uri.getQueryParameter("label");

        hour = Math.max(0, Math.min(hour, 23));
        minute = Math.max(0, Math.min(minute, 59));

        timePicker.setHour(hour);
        timePicker.setMinute(minute);

        if (label != null && !label.trim().isEmpty()) {
            labelInput.setText(label.trim());
        }

        if (!AlarmScheduler.canScheduleExact(this)) {
            showExactAlarmPermission();
            return;
        }

        createAlarm(
                hour,
                minute,
                labelInput.getText().toString()
        );
    }

    private void createAlarm(
            int hour,
            int minute,
            String rawLabel
    ) {
        String label =
                rawLabel == null || rawLabel.trim().isEmpty()
                        ? "Wake up"
                        : rawLabel.trim();

        long trigger = AlarmScheduler.nextOccurrence(hour, minute);

        try {
            AlarmScheduler.schedule(this, trigger, label);
        } catch (SecurityException error) {
            showExactAlarmPermission();
            return;
        }

        refreshStatus();

        Toast.makeText(
                this,
                String.format(
                        "Alarm created for %02d:%02d",
                        hour,
                        minute
                ),
                Toast.LENGTH_LONG
        ).show();
    }

    private void refreshStatus() {
        statusText.setText(AlarmScheduler.status(this));
    }

    private void refreshPermissionState() {
        permissionButton.setVisibility(
                AlarmScheduler.canScheduleExact(this)
                        ? Button.GONE
                        : Button.VISIBLE
        );
    }

    private void showExactAlarmPermission() {
        try {
            startActivity(
                    AlarmScheduler.exactAlarmSettingsIntent(this)
            );
        } catch (Exception error) {
            Toast.makeText(
                    this,
                    "Open Settings → Apps → Special access → "
                            + "Alarms & reminders.",
                    Toast.LENGTH_LONG
            ).show();
        }
    }

    private void requestNotificationPermissionIfNeeded() {
        if (
                Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(
                        Manifest.permission.POST_NOTIFICATIONS
                ) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(
                    new String[]{
                            Manifest.permission.POST_NOTIFICATIONS
                    },
                    NOTIFICATION_PERMISSION_REQUEST
            );
        }
    }

    private static int parseInt(
            String value,
            int fallback
    ) {
        try {
            return Integer.parseInt(value);
        } catch (Exception ignored) {
            return fallback;
        }
    }
}
