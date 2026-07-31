package com.sophyane.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

public final class AlarmReceiver extends BroadcastReceiver {
    private static final String CHANNEL_ID = "wake_up_alarm";
    private static final int NOTIFICATION_ID = 7001;

    @Override
    public void onReceive(Context context, Intent intent) {
        String label = intent.getStringExtra("label");

        if (label == null || label.trim().isEmpty()) {
            label = "Wake up";
        }

        createChannel(context);

        Intent ringIntent = new Intent(
                context,
                RingActivity.class
        )
                .putExtra("label", label)
                .addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK
                                | Intent.FLAG_ACTIVITY_CLEAR_TOP
                                | Intent.FLAG_ACTIVITY_SINGLE_TOP
                );

        PendingIntent fullScreenIntent =
                PendingIntent.getActivity(
                        context,
                        7101,
                        ringIntent,
                        PendingIntent.FLAG_UPDATE_CURRENT
                                | PendingIntent.FLAG_IMMUTABLE
                );

        Notification notification =
                new Notification.Builder(context, CHANNEL_ID)
                        .setSmallIcon(R.drawable.ic_alarm)
                        .setContentTitle(label)
                        .setContentText("Sophyane wake-up alarm")
                        .setCategory(Notification.CATEGORY_ALARM)
                        .setPriority(Notification.PRIORITY_MAX)
                        .setVisibility(Notification.VISIBILITY_PUBLIC)
                        .setOngoing(true)
                        .setAutoCancel(false)
                        .setFullScreenIntent(fullScreenIntent, true)
                        .setContentIntent(fullScreenIntent)
                        .build();

        NotificationManager manager =
                context.getSystemService(
                        NotificationManager.class
                );

        manager.notify(NOTIFICATION_ID, notification);

        try {
            context.startActivity(ringIntent);
        } catch (Exception ignored) {
            // The full-screen notification remains available.
        }
    }

    private static void createChannel(Context context) {
        if (Build.VERSION.SDK_INT < 26) {
            return;
        }

        NotificationChannel channel =
                new NotificationChannel(
                        CHANNEL_ID,
                        context.getString(
                                R.string.alarm_channel_name
                        ),
                        NotificationManager.IMPORTANCE_HIGH
                );

        channel.setDescription(
                context.getString(
                        R.string.alarm_channel_description
                )
        );
        channel.enableVibration(true);
        channel.setLockscreenVisibility(
                Notification.VISIBILITY_PUBLIC
        );
        channel.setBypassDnd(true);

        NotificationManager manager =
                context.getSystemService(
                        NotificationManager.class
                );

        manager.createNotificationChannel(channel);
    }

    public static void cancelNotification(Context context) {
        NotificationManager manager =
                context.getSystemService(
                        NotificationManager.class
                );

        manager.cancel(NOTIFICATION_ID);
    }
}
