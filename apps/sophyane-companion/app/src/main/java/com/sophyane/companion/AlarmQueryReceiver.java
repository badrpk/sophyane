package com.sophyane.companion;

import android.app.Activity;
import android.app.AlarmManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;

public final class AlarmQueryReceiver extends BroadcastReceiver {
    public static final String ACTION_QUERY =
            "com.sophyane.companion.QUERY_ALARM";

    private static final String PREFS = "sophyane_alarm";
    private static final String KEY_TRIGGER = "trigger";
    private static final String KEY_LABEL = "label";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (
                intent == null
                || !ACTION_QUERY.equals(intent.getAction())
        ) {
            setResultCode(Activity.RESULT_CANCELED);
            setResultData("unsupported_action");
            return;
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

        Bundle result = new Bundle();
        result.putInt("scheduled", scheduled ? 1 : 0);
        result.putLong("trigger_millis", trigger);
        result.putString(
                "label",
                label == null ? "" : label
        );
        result.putString("source", source);

        setResultCode(Activity.RESULT_OK);
        setResultData("alarm_status");
        setResultExtras(result);
    }
}
