package com.sophyane.companion;

import android.app.AlarmManager;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;

public final class AlarmStatusProvider extends ContentProvider {
    public static final String AUTHORITY =
            "com.sophyane.companion.alarmstatus";

    public static final Uri STATUS_URI =
            Uri.parse("content://" + AUTHORITY + "/status");

    private static final String PREFS = "sophyane_alarm";
    private static final String KEY_TRIGGER = "trigger";
    private static final String KEY_LABEL = "label";

    private static final String[] COLUMNS = {
            "scheduled",
            "trigger_millis",
            "label",
            "source"
    };

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Cursor query(
            Uri uri,
            String[] projection,
            String selection,
            String[] selectionArgs,
            String sortOrder
    ) {
        if (!"/status".equals(uri.getPath())) {
            throw new IllegalArgumentException(
                    "Unsupported URI: " + uri
            );
        }

        Context context = getContext();

        if (context == null) {
            return new MatrixCursor(COLUMNS);
        }

        SharedPreferences preferences =
                context.getSharedPreferences(
                        PREFS,
                        Context.MODE_PRIVATE
                );

        long savedTrigger =
                preferences.getLong(KEY_TRIGGER, 0L);

        String label =
                preferences.getString(KEY_LABEL, "Wake up");

        AlarmManager manager =
                (AlarmManager) context.getSystemService(
                        Context.ALARM_SERVICE
                );

        AlarmManager.AlarmClockInfo next =
                manager == null
                        ? null
                        : manager.getNextAlarmClock();

        long trigger = savedTrigger;
        String source = "companion_preferences";

        /*
         * Prefer Android's actual next AlarmClock when it agrees with the
         * Companion alarm or when the saved value is absent. This avoids
         * claiming an expired/cancelled preference is still active.
         */
        if (next != null) {
            long systemTrigger = next.getTriggerTime();

            if (
                    trigger <= System.currentTimeMillis()
                    || Math.abs(systemTrigger - trigger) < 60_000L
            ) {
                trigger = systemTrigger;
                source = "android_alarm_manager";
            }
        }

        boolean scheduled =
                trigger > System.currentTimeMillis();

        if (!scheduled) {
            trigger = 0L;
            label = "";
            source = "none";
        }

        MatrixCursor cursor =
                new MatrixCursor(COLUMNS, 1);

        cursor.addRow(
                new Object[]{
                        scheduled ? 1 : 0,
                        trigger,
                        label == null ? "" : label,
                        source
                }
        );

        return cursor;
    }

    @Override
    public String getType(Uri uri) {
        if ("/status".equals(uri.getPath())) {
            return "vnd.android.cursor.item/"
                    + "vnd.com.sophyane.companion.alarm-status";
        }

        return null;
    }

    @Override
    public Uri insert(
            Uri uri,
            ContentValues values
    ) {
        throw new UnsupportedOperationException(
                "Alarm status is read-only."
        );
    }

    @Override
    public int delete(
            Uri uri,
            String selection,
            String[] selectionArgs
    ) {
        throw new UnsupportedOperationException(
                "Alarm status is read-only."
        );
    }

    @Override
    public int update(
            Uri uri,
            ContentValues values,
            String selection,
            String[] selectionArgs
    ) {
        throw new UnsupportedOperationException(
                "Alarm status is read-only."
        );
    }
}
