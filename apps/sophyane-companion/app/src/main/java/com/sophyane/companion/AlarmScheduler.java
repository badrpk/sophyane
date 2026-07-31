package com.sophyane.companion;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.provider.Settings;

import java.text.DateFormat;
import java.util.Calendar;
import java.util.Date;

public final class AlarmScheduler {
    private static final String PREFS = "sophyane_alarm";
    private static final String KEY_TRIGGER = "trigger";
    private static final String KEY_LABEL = "label";
    private static final int REQUEST_CODE = 7001;

    private AlarmScheduler() {}

    public static boolean canScheduleExact(Context context) {
        AlarmManager manager =
                (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);

        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S
                || manager.canScheduleExactAlarms();
    }

    public static long nextOccurrence(int hour, int minute) {
        Calendar now = Calendar.getInstance();
        Calendar target = Calendar.getInstance();

        target.set(Calendar.HOUR_OF_DAY, hour);
        target.set(Calendar.MINUTE, minute);
        target.set(Calendar.SECOND, 0);
        target.set(Calendar.MILLISECOND, 0);

        if (!target.after(now)) {
            target.add(Calendar.DAY_OF_YEAR, 1);
        }

        return target.getTimeInMillis();
    }

    public static void schedule(
            Context context,
            long triggerAtMillis,
            String label
    ) {
        AlarmManager manager =
                (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);

        Intent alarmIntent = new Intent(context, AlarmReceiver.class)
                .putExtra("label", label)
                .putExtra("trigger", triggerAtMillis);

        PendingIntent alarmPendingIntent = PendingIntent.getBroadcast(
                context,
                REQUEST_CODE,
                alarmIntent,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE
        );

        Intent showIntent = new Intent(context, MainActivity.class);
        PendingIntent showPendingIntent = PendingIntent.getActivity(
                context,
                REQUEST_CODE + 1,
                showIntent,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE
        );

        AlarmManager.AlarmClockInfo info =
                new AlarmManager.AlarmClockInfo(
                        triggerAtMillis,
                        showPendingIntent
                );

        manager.setAlarmClock(info, alarmPendingIntent);

        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putLong(KEY_TRIGGER, triggerAtMillis)
                .putString(KEY_LABEL, label)
                .apply();
    }

    public static void cancel(Context context) {
        AlarmManager manager =
                (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);

        Intent intent = new Intent(context, AlarmReceiver.class);

        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                context,
                REQUEST_CODE,
                intent,
                PendingIntent.FLAG_NO_CREATE
                        | PendingIntent.FLAG_IMMUTABLE
        );

        if (pendingIntent != null) {
            manager.cancel(pendingIntent);
            pendingIntent.cancel();
        }

        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .clear()
                .apply();
    }

    public static void restore(Context context) {
        SharedPreferences preferences =
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        long trigger = preferences.getLong(KEY_TRIGGER, 0L);
        String label = preferences.getString(KEY_LABEL, "Wake up");

        if (trigger > System.currentTimeMillis() && canScheduleExact(context)) {
            schedule(context, trigger, label);
        }
    }

    public static String status(Context context) {
        SharedPreferences preferences =
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        long trigger = preferences.getLong(KEY_TRIGGER, 0L);
        String label = preferences.getString(KEY_LABEL, "Wake up");

        if (trigger <= System.currentTimeMillis()) {
            return "No future alarm scheduled.";
        }

        return "Next alarm:\n"
                + label
                + "\n"
                + DateFormat.getDateTimeInstance(
                        DateFormat.FULL,
                        DateFormat.SHORT
                ).format(new Date(trigger));
    }

    public static Intent exactAlarmSettingsIntent(Context context) {
        Intent intent = new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM);
        intent.setData(
                android.net.Uri.parse("package:" + context.getPackageName())
        );
        return intent;
    }
}
