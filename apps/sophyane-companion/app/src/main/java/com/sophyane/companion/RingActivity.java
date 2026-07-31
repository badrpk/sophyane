package com.sophyane.companion;

import android.app.Activity;
import android.media.AudioAttributes;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.WindowManager;
import android.widget.TextView;

import java.text.DateFormat;
import java.util.Date;

public final class RingActivity extends Activity {
    private Ringtone ringtone;
    private Vibrator vibrator;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        setShowWhenLocked(true);
        setTurnScreenOn(true);

        getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                        | WindowManager.LayoutParams.FLAG_ALLOW_LOCK_WHILE_SCREEN_ON
                        | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        );

        setContentView(R.layout.activity_ring);

        String label = getIntent().getStringExtra("label");

        if (label == null || label.trim().isEmpty()) {
            label = "Wake up";
        }

        ((TextView) findViewById(R.id.alarmTitle))
                .setText(label);

        ((TextView) findViewById(R.id.alarmTime))
                .setText(
                        DateFormat.getTimeInstance(
                                DateFormat.SHORT
                        ).format(new Date())
                );

        findViewById(R.id.stopButton)
                .setOnClickListener(view -> stopAlarm());

        beginSound();
        beginVibration();
    }

    private void beginSound() {
        Uri sound = RingtoneManager.getDefaultUri(
                RingtoneManager.TYPE_ALARM
        );

        if (sound == null) {
            sound = RingtoneManager.getDefaultUri(
                    RingtoneManager.TYPE_NOTIFICATION
            );
        }

        ringtone = RingtoneManager.getRingtone(
                this,
                sound
        );

        if (ringtone == null) {
            return;
        }

        ringtone.setAudioAttributes(
                new AudioAttributes.Builder()
                        .setUsage(
                                AudioAttributes.USAGE_ALARM
                        )
                        .setContentType(
                                AudioAttributes.CONTENT_TYPE_SONIFICATION
                        )
                        .build()
        );

        if (android.os.Build.VERSION.SDK_INT >= 28) {
            ringtone.setLooping(true);
        }

        ringtone.play();
    }

    private void beginVibration() {
        vibrator = getSystemService(Vibrator.class);

        if (vibrator != null && vibrator.hasVibrator()) {
            vibrator.vibrate(
                    VibrationEffect.createWaveform(
                            new long[]{
                                    0,
                                    800,
                                    400,
                                    800,
                                    400
                            },
                            1
                    )
            );
        }
    }

    private void stopAlarm() {
        if (ringtone != null && ringtone.isPlaying()) {
            ringtone.stop();
        }

        if (vibrator != null) {
            vibrator.cancel();
        }

        AlarmReceiver.cancelNotification(this);
        AlarmScheduler.cancel(this);
        finishAndRemoveTask();
    }

    @Override
    protected void onDestroy() {
        if (isFinishing()) {
            if (ringtone != null) {
                ringtone.stop();
            }

            if (vibrator != null) {
                vibrator.cancel();
            }
        }

        super.onDestroy();
    }
}
