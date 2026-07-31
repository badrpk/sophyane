package com.sophyane.companion;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;

import org.json.JSONObject;

import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

public final class AlarmStatusFile {
    private static final String PREFS = "sophyane_alarm";
    private static final String KEY_TRIGGER = "trigger";
    private static final String KEY_LABEL = "label";

    private static final String FILE_NAME =
            "SophyaneAlarmStatus.json";

    private AlarmStatusFile() {}

    public static void writeCurrent(Context context) {
        SharedPreferences preferences =
                context.getSharedPreferences(
                        PREFS,
                        Context.MODE_PRIVATE
                );

        long trigger =
                preferences.getLong(KEY_TRIGGER, 0L);

        String label =
                preferences.getString(KEY_LABEL, "Wake up");

        boolean scheduled =
                trigger > System.currentTimeMillis();

        if (!scheduled) {
            trigger = 0L;
            label = "";
        }

        write(
                context,
                scheduled,
                trigger,
                label == null ? "" : label
        );
    }

    public static void write(
            Context context,
            boolean scheduled,
            long triggerMillis,
            String label
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return;
        }

        try {
            JSONObject payload = new JSONObject();

            payload.put("version", 1);
            payload.put("scheduled", scheduled);
            payload.put(
                    "trigger_millis",
                    scheduled ? triggerMillis : 0L
            );
            payload.put(
                    "label",
                    scheduled && label != null ? label : ""
            );
            payload.put(
                    "updated_millis",
                    System.currentTimeMillis()
            );
            payload.put(
                    "source",
                    "sophyane_companion"
            );

            ContentResolver resolver =
                    context.getContentResolver();

            Uri collection =
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI;

            Uri existing = findExisting(
                    resolver,
                    collection
            );

            Uri target;

            if (existing != null) {
                target = existing;
            } else {
                ContentValues values =
                        new ContentValues();

                values.put(
                        MediaStore.Downloads.DISPLAY_NAME,
                        FILE_NAME
                );
                values.put(
                        MediaStore.Downloads.MIME_TYPE,
                        "application/json"
                );
                values.put(
                        MediaStore.Downloads.RELATIVE_PATH,
                        "Download"
                );
                values.put(
                        MediaStore.Downloads.IS_PENDING,
                        1
                );

                target = resolver.insert(
                        collection,
                        values
                );
            }

            if (target == null) {
                return;
            }

            try (
                    OutputStream output =
                            resolver.openOutputStream(
                                    target,
                                    "wt"
                            )
            ) {
                if (output == null) {
                    return;
                }

                output.write(
                        payload.toString(2).getBytes(
                                StandardCharsets.UTF_8
                        )
                );
            }

            ContentValues complete =
                    new ContentValues();

            complete.put(
                    MediaStore.Downloads.IS_PENDING,
                    0
            );

            resolver.update(
                    target,
                    complete,
                    null,
                    null
            );
        } catch (Exception ignored) {
            // Status export must never prevent alarm scheduling.
        }
    }

    private static Uri findExisting(
            ContentResolver resolver,
            Uri collection
    ) {
        String[] projection = {
                MediaStore.Downloads._ID
        };

        String selection =
                MediaStore.Downloads.DISPLAY_NAME
                        + "=? AND "
                        + MediaStore.Downloads.RELATIVE_PATH
                        + "=?";

        String[] selectionArgs = {
                FILE_NAME,
                "Download/"
        };

        try (
                Cursor cursor = resolver.query(
                        collection,
                        projection,
                        selection,
                        selectionArgs,
                        null
                )
        ) {
            if (
                    cursor != null
                    && cursor.moveToFirst()
            ) {
                long id = cursor.getLong(0);

                return ContentUris.withAppendedId(
                        collection,
                        id
                );
            }
        } catch (Exception ignored) {
            return null;
        }

        return null;
    }
}
